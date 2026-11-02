# rapidetech-rustdesk-client

**Dépôt public sur GitHub** (`limaxrayxray/rapidetech-rustdesk-client`) :
aucune information interne ici (IP, noms de machines, chemins des LXC). Le
contexte du serveur RustDesk se trouve dans le dépôt gitea `rustdesk`.

Le fonctionnement est décrit dans `README.md`. Règles :

- Ne jamais modifier à la main les fichiers générés (`generator-*.yml`,
  `bridge.yml`, `third-party-*.yml`, `clear-cache.yml`, `.github/rdgen-*`).
  Modifier `tools/sync-rdgen.py` ou `config/client.json`, puis relancer le
  script.
- Si le script s'arrête sur « rdgen a changé », c'est voulu : une
  transformation ne trouve plus ce qu'elle attend. Lire le nouveau workflow
  rdgen et adapter le script. Ne pas assouplir le contrôle sans comprendre.
- Après une synchronisation, valider avec `actionlint`. Les avertissements
  qui existent déjà chez rdgen (vieille action, entrée `upload-tag`) sont
  attendus.
- `key` dans `config/client.json` est la clé **publique** du serveur. Le
  script refuse la clé et le serveur publics de RustDesk.
- Accès en écriture : une deploy key limitée à ce dépôt (alias SSH
  `github-rustdesk-client`). Aucun jeton API : les builds partent de la
  poussée d'un tag, et le suivi passe par l'API publique.
