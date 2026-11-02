#!/usr/bin/env python3
"""Régénère les workflows de build à partir de ceux de rdgen.

rdgen (github.com/bryangerlach/rdgen) suit les changements de RustDesk
(versions de Flutter, vcpkg, NDK, nouvelles étapes de build). Ses workflows
reçoivent leur configuration d'un serveur rdgen, par un zip chiffré, et lui
renvoient les binaires. Ce script les reprend presque tels quels et ne
remplace que ces deux points de branchement :

- la configuration vient de config/client.json, convertie dans
  .github/rdgen-env.json avec la même logique que le serveur rdgen
  (rdgenerator/views.py, generate_custom_client) ;
- les binaires partent dans une release GitHub `<version>-<patch>`.

Il ajoute aussi un contrôle qui fait échouer le build si le serveur et la clé
ne sont pas intégrés au client : l'étape de rdgen qui les pose est en
continue-on-error.

Usage : tools/sync-rdgen.py [--ref <branche|tag|sha de rdgen>]   (défaut : master)

Chaque transformation vérifie le nombre d'occurrences attendu. Si rdgen change
de structure, le script s'arrête au lieu de produire un workflow faux.
Python stdlib seulement.
"""

import argparse
import base64
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

RDGEN = "bryangerlach/rdgen"
THIS_REPO = "limaxrayxray/rapidetech-rustdesk-client"
ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows"

GENERATORS = ["generator-windows.yml", "generator-macos.yml",
              "generator-android.yml", "generator-linux.yml"]
VERBATIM = ["bridge.yml", "third-party-RustDeskTempTopMostWindow.yml",
            "clear-cache.yml"]
# Fichiers propres à ce dépôt, que ce script ne touche pas.
OWN = ["fetch-encrypted-secrets.yml", "release.yml"]

STEP = "      - "  # indentation des étapes dans les jobs rdgen


def die(msg):
    sys.exit(f"sync-rdgen: {msg}")


def resolve_ref(ref):
    if re.fullmatch(r"[0-9a-f]{40}", ref):
        return ref
    out = subprocess.run(
        ["git", "ls-remote", f"https://github.com/{RDGEN}", ref,
         f"refs/heads/{ref}", f"refs/tags/{ref}"],
        check=True, capture_output=True, text=True).stdout.split()
    if not out:
        die(f"référence rdgen introuvable : {ref}")
    return out[0]


def fetch(sha, path):
    url = f"https://raw.githubusercontent.com/{RDGEN}/{sha}/{path}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8")


# --- Configuration : portage de generate_custom_client (rdgen views.py) ---

def build_env(cfg):
    yn = lambda b: "Y" if b else "N"
    server = cfg.get("serverIP") or "rs-ny.rustdesk.com"
    key = cfg.get("key") or "OeVuKk5nlHiXp+APNn0Y3pC1Iwpwn44JGqrQCsWqmBw="
    if server == "rs-ny.rustdesk.com" or key.startswith("OeVuKk5n"):
        die("serverIP et key doivent être ceux du serveur rapidetech")
    api_server = cfg.get("apiServer") or server + ":21114"
    appname_display = cfg.get("appname") or "rustdesk"
    appname = re.sub(r"[:|\\/]", "", appname_display).replace(" ", "")
    filename = cfg.get("exename") or "rustdesk"
    filename = re.sub(r"[^\w\s-]", "_", filename).strip().replace(" ", "_")
    if not (appname.isascii() and filename.isascii()):
        die("appname et exename doivent être en ASCII")
    remove_notif = cfg.get("removeNewVersionNotif", False)
    if cfg.get("update_public_key"):
        remove_notif = False
    hidecm = cfg.get("hidecm", False)

    custom = {}
    direction = cfg.get("direction", "both")
    if direction != "Both":  # sic : rdgen compare à "Both"
        custom["conn-type"] = direction
    if cfg.get("installation") == "installationN":
        custom["disable-installation"] = "Y"
    if cfg.get("settings") == "settingsN":
        custom["disable-settings"] = "Y"
    if appname:
        custom["app-name"] = appname_display
    custom["override-settings"] = {}
    custom["default-settings"] = {}
    if cfg.get("permanentPassword"):
        custom["password"] = cfg["permanentPassword"]
    theme = cfg.get("theme", "system")
    if theme != "system":
        where = "override-settings" if cfg.get("themeDorO") == "override" else "default-settings"
        custom[where]["theme"] = theme
    custom["enable-lan-discovery"] = yn(not cfg.get("denyLan", False))
    custom["allow-auto-disconnect"] = yn(cfg.get("autoClose", False))

    where = "override-settings" if cfg.get("permissionsDorO") == "override" else "default-settings"
    s = custom[where]
    s["access-mode"] = cfg.get("permissionsType", "custom")
    for opt, flag, default in [
            ("enable-keyboard", "enableKeyboard", True),
            ("enable-clipboard", "enableClipboard", True),
            ("enable-file-transfer", "enableFileTransfer", True),
            ("enable-audio", "enableAudio", True),
            ("enable-tunnel", "enableTCP", True),
            ("enable-remote-restart", "enableRemoteRestart", True),
            ("enable-record-session", "enableRecording", True),
            ("enable-block-input", "enableBlockingInput", True),
            ("allow-remote-config-modification", "enableRemoteModi", False),
            ("direct-server", "enableDirectIP", False)]:
        s[opt] = yn(cfg.get(flag, default))
    s["verification-method"] = "use-permanent-password" if hidecm else "use-both-passwords"
    s["approve-mode"] = cfg.get("passApproveMode", "password-click")
    s["allow-hide-cm"] = yn(hidecm)
    for opt, flag in [("allow-remove-wallpaper", "removeWallpaper"),
                      ("enable-remote-printer", "enablePrinter"),
                      ("enable-camera", "enableCamera"),
                      ("enable-terminal", "enableTerminal")]:
        s[opt] = yn(cfg.get(flag, True))
    if where == "override-settings" and direction == "incoming":
        s["custom-rendezvous-server"] = server
        s["api-server"] = api_server
    for field, target in [("defaultManual", "default-settings"),
                          ("overrideManual", "override-settings")]:
        for line in cfg.get(field, "").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                custom[target][k.strip()] = v.strip()

    def image(field):
        path = cfg.get(field)
        if not path:
            return "false"
        if not (ROOT / path).is_file():
            die(f"{field} : {path} introuvable dans le dépôt")
        return f"https://raw.githubusercontent.com/{THIS_REPO}/master/{path}"

    compname = (cfg.get("compname") or "Purslane Ltd").replace("&", "\\&")
    return {
        "server": server,
        "serverPort": str(cfg.get("serverPort") or "21116"),
        "key": key,
        "apiServer": api_server,
        "custom": base64.b64encode(json.dumps(custom).encode("ascii")).decode("ascii"),
        "uuid": "rapidetech",
        "iconlink_url": image("icon"), "iconlink_uuid": "", "iconlink_file": "",
        "logolink_url": image("logo"), "logolink_uuid": "", "logolink_file": "",
        "privacylink_url": image("privacy"), "privacylink_uuid": "", "privacylink_file": "",
        "appname": appname,
        "genurl": "",
        "urlLink": cfg.get("urlLink") or "https://rustdesk.com",
        "downloadLink": cfg.get("downloadLink") or "https://rustdesk.com/download",
        "delayFix": str(cfg.get("delayFix", True)).lower(),
        # Ni 'true' (serveur rdgen) ni 'false' (serveur d'API) : les deux
        # étapes d'envoi de rdgen sont sautées, la release GitHub les remplace.
        "rdgen": "github",
        "xOffline": str(cfg.get("xOffline", False)).lower(),
        "removeNewVersionNotif": str(remove_notif).lower(),
        "update_public_key": cfg.get("update_public_key", ""),
        "compname": compname,
        "androidappid": cfg.get("androidappid") or "com.carriez.flutter_hbb",
        "filename": filename,
    }


# --- Transformation des workflows ---

def steps(lines):
    """(début, fin, nom) de chaque étape indentée comme celles de rdgen."""
    out, i = [], 0
    while i < len(lines):
        if not lines[i].startswith(STEP):
            i += 1
            continue
        j = i + 1
        while j < len(lines) and (not lines[j].strip()
                                  or (lines[j].startswith("        ")
                                      and not lines[j].startswith(STEP))):
            j += 1
        while j > i + 1 and not lines[j - 1].strip():
            j -= 1  # les lignes vides finales n'appartiennent pas à l'étape
        m = re.match(r"\s+- name: (.*)", lines[i])
        name = m.group(1).strip() if m else next(
            (re.match(r"\s+name: (.*)", l).group(1).strip()
             for l in lines[i:j] if re.match(r"        name: ", l)), "")
        out.append((i, j, name))
        i = j
    return out


def verify_step():
    return """\
      - name: Vérifier le serveur et la clé intégrés (rapidetech)
        shell: bash
        env:
          EXPECT_SERVER: ${{ env.server }}
          EXPECT_KEY: ${{ env.key }}
        run: |
          f=./libs/hbb_common/src/config.rs
          fail() { echo "::error::$1"; exit 1; }
          [ -n "$EXPECT_SERVER" ] && [ -n "$EXPECT_KEY" ] || fail "serveur ou clé absents de la configuration"
          grep -qF "\\"$EXPECT_SERVER\\"" "$f" || fail "serveur $EXPECT_SERVER absent de $f"
          grep -qF "$EXPECT_KEY" "$f" || fail "clé du serveur absente de $f"
          ! grep -qF rs-ny.rustdesk.com "$f" || fail "le serveur public de RustDesk est encore dans $f"
          ! grep -qF OeVuKk5nlHiXp+APNn0Y3pC1Iwpwn44JGqrQCsWqmBw= "$f" || fail "la clé publique de RustDesk est encore dans $f"
          echo "OK : $EXPECT_SERVER et sa clé sont intégrés"
""".splitlines()


def release_steps(upload_block):
    files = []
    for line in upload_block:
        for path in re.findall(r'file=@([^"]+)"', line):
            if path not in [p for p, _ in files]:
                files.append((path, line.rstrip().endswith("|| true")))
    if not files:
        die("aucun fichier trouvé dans une étape « send file to rdgen server »")
    out = ["      - name: Vérifier les fichiers à publier (rapidetech)",
           "        shell: bash",
           "        run: |"]
    for path, optional in files:
        if optional:
            out.append(f'          [ -f "{path}" ] || echo "::warning::{path} absent (facultatif)"')
        else:
            out.append(f'          [ -f "{path}" ] || {{ echo "::error::{path} absent"; exit 1; }}')
    out += ["",
            "      - name: Publier dans la release GitHub (rapidetech)",
            "        uses: softprops/action-gh-release@v3",
            "        with:",
            "          tag_name: ${{ inputs.version }}-${{ inputs.patch }}",
            "          prerelease: true",
            "          files: |"]
    out += ["            " + p.replace("$GITHUB_WORKSPACE/", "./") for p, _ in files]
    return out


def expect(n, what, name, minimum=1, exact=None):
    if (exact is not None and n != exact) or n < minimum:
        want = exact if exact is not None else f">= {minimum}"
        die(f"{name} : {what} trouvé {n} fois, attendu {want}. rdgen a changé, adapter ce script.")


def transform(name, text, sha):
    # Patchs que rdgen télécharge pendant le build : même commit que les workflows.
    text, n = re.subn(r"bryangerlach/rdgen/refs/heads/master/", f"bryangerlach/rdgen/{sha}/", text)
    if "bryangerlach/rdgen/refs/heads/" in text:
        die(f"{name} : URL de patch rdgen sur une autre branche que master")

    # Icône et logo : URL directe, plus le get_png du serveur rdgen.
    text, n = re.subn(
        r'\$\{\{ env\.(\w+?)link_url \}\}/get_png\?filename=\$\{\{ env\.\1link_file \}\}"?&"?uuid=\$\{\{ env\.\1link_uuid \}\}',
        r"${{ env.\1link_url }}", text)
    expect(n, "téléchargement get_png", name)
    if "get_png" in text:
        die(f"{name} : un get_png n'a pas été réécrit")

    # removeNewVersionNotif : le sed de rdgen supprime de « let (request, url) = »
    # au prochain « Ok(()) ». Sur 1.4.x et 1.5.0, c'était la fin de
    # do_check_software_update. Sur 1.5.1, le prochain Ok(()) est 1 100 lignes
    # plus bas, et le code ne compile plus. On neutralise plutôt la fonction en
    # tête, avec perl, présent sur les 3 OS (le sed BSD de macOS échouait).
    text, n = text.replace(
        "sed -i '/let (request, url) =/,/Ok(())/{/Ok(())/!d}' ./src/common.rs",
        "perl -0777 -i.bak -pe 's/(pub async fn do_check_software_update\\(\\) -> hbb_common::ResultType<\\(\\)> \\{\\r?\\n)/$1    return Ok(());\\n/' ./src/common.rs"
    ), text.count("sed -i '/let (request, url) =/,/Ok(())/{/Ok(())/!d}' ./src/common.rs")
    expect(n, "sed removeNewVersionNotif sur common.rs", name)

    # zip_url facultatif, entrée patch pour le tag de release.
    text, n = re.subn(r"(\n      zip_url:\n        description: [^\n]*\n        required: )true",
                      r"\1false", text)
    expect(n, "entrée zip_url", name, exact=1)
    text, n = re.subn(r"\n    inputs:\n",
                      "\n    inputs:\n"
                      "      patch:\n"
                      "        description: 'numéro de build rapidetech (release <version>-<patch>)'\n"
                      "        required: false\n"
                      "        default: '1'\n"
                      "        type: string\n", text, count=1)
    expect(n, "bloc inputs", name, exact=1)
    text, n = re.subn(r"^run-name: (.*?)\s*$",
                      r"run-name: \1 ${{ inputs.version }}-${{ inputs.patch }}",
                      text, count=1, flags=re.M)
    expect(n, "run-name", name, exact=1)

    lines = text.split("\n")
    st = steps(lines)
    load = [s for s in st if s[2] == "Load Secrets"]
    cleanup = [s for s in st if s[2] == "Finalize and Cleanup zip/json"]
    server = [s for s in st if s[2] == "set server, serverPort, key, and apiserver"]
    upload = [s for s in st if s[2] == "send file to rdgen server"]
    expect(len(load), "étape Load Secrets", name)
    expect(len(cleanup), "étape Finalize and Cleanup", name)
    expect(len(server), "étape set server", name)
    expect(len(upload), "étape send file to rdgen server", name)

    # Modifications de la fin vers le début, pour garder les indices valides.
    edits = [(s, e, []) for s, e, _ in cleanup]
    edits += [(e, e, [""] + verify_step()) for _, e, _ in server]
    edits += [(e, e, [""] + release_steps(lines[s:e])) for s, e, _ in upload]
    for s, e, new in sorted(edits, key=lambda x: x[0], reverse=True):
        if not new:  # suppression : avec la ligne vide qui suit
            while e < len(lines) and not lines[e].strip():
                e += 1
        lines[s:e] = new
    return "\n".join(lines)


def header(sha, generated):
    what = "Généré" if generated else "Copié tel quel"
    return (f"# {what} par tools/sync-rdgen.py depuis {RDGEN}@{sha[:12]}.\n"
            f"# Ne pas modifier à la main : modifier le script ou config/client.json.\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ref", default="master", help="branche, tag ou sha de rdgen")
    args = ap.parse_args()

    cfg = json.loads((ROOT / "config" / "client.json").read_text(encoding="utf-8"))
    env = build_env(cfg)
    sha = resolve_ref(args.ref)

    WF.mkdir(parents=True, exist_ok=True)
    for name in GENERATORS:
        out = header(sha, True) + transform(name, fetch(sha, f".github/workflows/{name}"), sha)
        (WF / name).write_text(out, encoding="utf-8")
    for name in VERBATIM:
        (WF / name).write_text(header(sha, False) + fetch(sha, f".github/workflows/{name}"),
                               encoding="utf-8")
    (ROOT / ".github" / "rdgen-env.json").write_text(
        json.dumps(env, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (ROOT / ".github" / "rdgen-ref").write_text(sha + "\n", encoding="utf-8")

    known = set(GENERATORS + VERBATIM + OWN)
    for f in sorted(WF.glob("*.yml")):
        if f.name not in known:
            print(f"attention : {f.relative_to(ROOT)} n'est géré ni par ce script ni à la main")
    print(f"rdgen@{sha[:12]} → {len(GENERATORS)} générateurs, {len(VERBATIM)} copies, rdgen-env.json")


if __name__ == "__main__":
    main()
