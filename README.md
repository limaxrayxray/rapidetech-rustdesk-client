# Support rapidetech — client RustDesk personnalisé

Build du client [RustDesk](https://github.com/rustdesk/rustdesk) « Support
rapidetech », préconfiguré pour le serveur `rust.rapidetech.ca`, sur GitHub
Actions et sans serveur [rdgen](https://github.com/bryangerlach/rdgen).

## Principe

Les workflows de build sont ceux de rdgen, régénérés par
`tools/sync-rdgen.py`. rdgen suit les changements de RustDesk (versions de
Flutter, vcpkg, NDK, nouvelles étapes de build) : on profite de ses mises à
jour sans les reporter à la main.

Le script ne remplace que ce qui dépend du serveur rdgen :

| rdgen | ici |
|---|---|
| configuration dans un zip chiffré, téléchargé depuis le serveur | `config/client.json`, converti en `.github/rdgen-env.json` avec la logique de rdgen |
| icône et logo servis par le serveur | `img/logo.png` de ce dépôt |
| binaires renvoyés au serveur | release GitHub `<version>-<patch>` |

Il fige aussi chaque action tierce (`uses: owner/repo@v3`) sur le SHA de son
commit, avec l'étiquette en commentaire. Une étiquette peut être déplacée vers
du code malveillant (`tj-actions/changed-files`, 2025), et ces workflows
produisent un outil de prise de contrôle à distance installé chez des clients.
Les SHA sont recalculés à chaque synchronisation : relire leurs changements
dans le `git diff`.

Il ajoute enfin un contrôle qui fait échouer le build si le serveur et la clé
ne sont pas intégrés au client. Dans rdgen, l'étape qui les pose est en
`continue-on-error` : un échec y passerait inaperçu et produirait un client
réglé sur les serveurs publics de RustDesk.

## Écarts volontaires avec rdgen

- **removeNewVersionNotif** : le `sed` de rdgen supprime de
  `let (request, url) =` au prochain `Ok(())` de `src/common.rs`. Sur
  RustDesk 1.5.1, ce n'est plus la fin de `do_check_software_update`, mais
  1 100 lignes plus bas, et le code ne compile plus. Le script le remplace par
  un `return Ok(());` en tête de la fonction, avec `perl`. En 1.5.x, la
  vérification de mise à jour est de toute façon désactivée pour les clients
  personnalisés (`is_custom_client()`).
- **Identifiant Android** : rdgen pose `namespace "com.carriez.flutter_hbb"`
  (le paquet de la classe `R`), puis le remplace en même temps que
  `applicationId`. Le code Kotlin ne trouve plus `R` et l'APK ne compile pas.
  Le script ne change que `applicationId` (`ca.rapidetech.support`).
- **Libellé Android** : rdgen met le nom interne (`Supportrapidetech`) dans
  les `android:label` du manifeste, affichés sous l'icône et dans les
  réglages d'accessibilité. Le script y met le nom affiché
  (`appname_display` dans `rdgen-env.json`). Ce nom est donc limité aux
  lettres, chiffres, espaces, `.`, `_` et `-`.
- **`custom_.txt` du .deb** : RustDesk lit ce fichier (nom affiché,
  permissions par défaut) dans le dossier de son exécutable,
  `/usr/share/<appname>/`. rdgen le dépose dans `/usr/share/rustdesk/` et ne
  le copie à côté de l'exécutable que pour rpm, AppImage et flatpak. Le
  script l'ajoute au .deb après sa création (`dpkg-deb -R` / `-b`). Le
  serveur et la clé, compilés dans le binaire, n'en dépendent pas.
- **Linux unattended-wayland** (`libdrmtap`, ajouté par rdgen le
  2026-10-31) : son empaquetage échoue avec un nom d'application
  personnalisé. Le job est désactivé (`if: false`), sauf si
  `linuxUnattendedWayland` vaut `true` dans `config/client.json`.

## Fichiers

| Fichier | Rôle | Modifié par |
|---|---|---|
| `config/client.json` | configuration du client (nom, serveur, clé, permissions) | à la main |
| `tools/sync-rdgen.py` | régénère les workflows depuis rdgen | à la main |
| `.github/workflows/generator-*.yml`, `bridge.yml`, `third-party-*.yml`, `clear-cache.yml` | workflows rdgen | **le script uniquement** |
| `.github/rdgen-env.json`, `.github/rdgen-ref` | configuration convertie, commit rdgen utilisé | **le script uniquement** |
| `.github/workflows/fetch-encrypted-secrets.yml`, `.github/actions/decrypt-secrets/` | remplacent ceux de rdgen : publient et chargent `rdgen-env.json` | à la main |
| `.github/workflows/release.yml` | crée la release et lance les générateurs à la poussée d'un tag | à la main |

## Nouvelle version de RustDesk

```sh
tools/sync-rdgen.py                # workflows rdgen actuels (ou --ref <sha>)
git diff                           # relire ce qui a changé chez rdgen
git commit -am "Synchroniser avec rdgen <sha>"
git tag 1.5.1-1 && git push origin master 1.5.1-1
```

Le tag `<version RustDesk>-<patch>` crée une pré-release, puis lance les
générateurs Windows, macOS, Android et Linux, qui y déposent leurs binaires.
Pour rebâtir la même version (config modifiée, build raté), on incrémente le
patch : `1.5.1-2`. Le workflow `Release` se relance aussi à la main sur un
tag existant, en choisissant les plateformes.

Une fois les binaires testés, on passe la pré-release en release. Les liens
`https://github.com/limaxrayxray/rapidetech-rustdesk-client/releases/latest/download/<fichier>`
pointent alors vers la nouvelle version.

## Binaires produits

| Plateforme | Fichiers |
|---|---|
| Windows | `rapidetech-support.exe`, `rapidetech-support.msi` |
| macOS | `rapidetech-support-x86_64.dmg`, `rapidetech-support-aarch64.dmg` |
| Android | `rapidetech-support-<arch>.apk` |
| Linux | `.deb`, `.rpm`, `.pkg.tar.zst`, `.AppImage`, `.flatpak` |

Les binaires ne sont pas signés : Windows affiche l'avertissement SmartScreen,
macOS demande une ouverture manuelle (clic droit → Ouvrir). Pour les signer,
il faut configurer les secrets `SIGN_*`, `MACOS_P12_*` et `ANDROID_*`
attendus par les workflows rdgen.

## Note sur le nom

Comme dans rdgen, le nom interne (`appname`) est le nom affiché sans les
espaces : `Supportrapidetech`. Le nom affiché, « Support rapidetech », passe
par `custom.txt`. Le dépôt d'origine utilisait le nom avec espace et devait
corriger à part les clés de registre Windows qui en souffraient.
