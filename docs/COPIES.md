# Còpies de seguretat

Les còpies es xifren amb una **clau pública GPG**. La torre només té la pública: pot xifrar però **no desxifrar**.
Així, si algú entra a la torre, les còpies (també les de fora) continuen il·legibles.

## Preparació (un cop)
1. Al TEU ordinador (no a la torre): `gpg --full-generate-key` (RSA 3072 o més, amb contrasenya) i
   `gpg --armor --export <id> > club-publica.asc`.
2. Guarda la **clau privada** fora de la torre, amb còpia (gestor de contrasenyes o paper): `gpg --armor --export-secret-keys <id>`.
   **Sense ella les còpies no es poden recuperar.**
3. A la torre: `gpg --import club-publica.asc` (i marca-la com a fiable: `gpg --edit-key <id> trust`).
4. Crea `~/.config/club-gestio/backup.env` amb `CLUB_BACKUP_GPG_RECIPIENT=<id>` i, si vols còpia externa, `CLUB_BACKUP_REMOTE=usuari@host:/ruta`.
5. Prova: `scripts/club-backup.sh run`. Activa el temporitzador:
   `cp scripts/systemd/club-backup.* ~/.config/systemd/user/ && systemctl --user enable --now club-backup.timer`.

## Què conté cada còpia
Volcat de PostgreSQL (només el rol sense privilegis hi accedeix) i les claus `CLUB_FIELD_KEY`/`CLUB_INDEX_KEY`, tot dins del fitxer xifrat.
Els camps personals ja van xifrats dins del volcat: hi ha doble capa.

## Restaurar i comprovar (al teu ordinador, amb la clau privada)
`scripts/club-backup.sh restore-test club-AAAAMMDD-HHMMSS.tar.gpg` desxifra, restaura en un PostgreSQL temporal i verifica la cadena d'auditoria.
**Fes aquesta prova de tant en tant:** una còpia que mai s'ha restaurat no és una còpia.

## Prova automàtica
`scripts/test-backup.sh` fa tot el cicle amb una clau i una base de dades temporals (còpia, absència de dades en clar, restauració,
detecció d'alteració, impossibilitat de desxifrar sense la privada i rotació).
