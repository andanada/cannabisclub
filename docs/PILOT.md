# Pla de pilot (1-2 setmanes)

Objectiu: comprovar amb maquinari real i gent real (però **dades ficticies**) que el programa, les còpies i les alertes funcionen abans de tractar dades de socis.

## Condicions

- Servidor de pilot separat o amb una base de dades de pilot; **cap dada personal real**: socis inventats, documents de prova, fotos de mostra.
- **TOTP activat** (no `CLUB_TOTP=0`): tots els usuaris del pilot entren amb codi de l'app d'autenticació.
- HTTPS real (nginx de `scripts/nginx/` o `tailscale serve`): sense això la bàscula i l'NFC no funcionen.
- Còpies, remot i alertes configurats com en producció (`docs/COPIES.md`, `docs/PRODUCCIO.md`).
- Una persona responsable del pilot i un registre diari d'incidències (data, què, gravetat).

## Setmana 1: funcionament

| Dia | Prova | Criteri d'èxit |
|---|---|---|
| 1 | Instal·lació amb `requirements.lock`, `preparar-bd`, `crear-admin`, TOTP | `/salut` OK, entrada amb TOTP |
| 1 | Timers de còpia, monitor i auditoria actius; `club-monitor.sh test` | arriba l'alerta de prova |
| 2 | Alta de 20 socis ficticis, quotes, productes, estoc, caixa | sense errors; quadra la caixa |
| 2-4 | Jornades simulades amb 2-3 treballadors: dispensar, caixa, fitxatge, inventari, informes | temps per dispensació, errors anotats |
| 3 | Entrada amb carnet RFID + PIN; bloqueig per PIN erroni; carnet perdut | bloqueja als 5 intents; retirat deixa de servir |
| 4 | Càrrega: 3 tauletes alhora | cap error 5xx |
| 5 | **Restauració de la còpia** al teu ordinador (`restore-test`) | auditoria íntegra, signatura OK |

## Setmana 2: maquinari, fallades i seguretat

### Bàscula WANT WT3002A

1. Connecta-la per USB/sèrie a una tauleta o PC amb Chrome/Edge sobre HTTPS. A **Configuració → Bàscules** crea un perfil (velocitat, bits de dades, paritat, parada, control de flux; mira el manual del model).
2. **Captura de lectura en brut**: al panell de prova, connecta i deixa que la bàscula emeti (o envia l'ordre de lectura). Copia la **comunicació en cru** (hex i text) per a cada cas: buida, pes estable (10 g, 50 g, 100 g amb peses de calibratge), pes inestable (toca el plat), sobrecàrrega, tara activada, canvi d'unitat (g/ct/oz), bàscula apagada/desconnectada.
3. Desa les captures a `docs/captures-bascula/` (fora de git si hi ha dades) amb: model, firmware, perfil sèrie, ordre enviada, bytes rebuts.
4. Comprova que el programa interpreta: pes correcte, estabilitat (marca d'inestable), unitat i signe. Anota discrepàncies amb la trama exacta: serviran per adaptar `frontend/bascula.js` (el protocol actual és el d'OHAUS i **no s'ha validat amb la WT3002A**).
5. Prova la tolerància de dispensació: dispensa 10 g amb el pes real a 10 g, 10,5 g i 12 g; la darrera ha de ser rebutjada segons el límit configurat.
6. Desconnecta el cable en mig d'una lectura: el programa ha d'indicar-ho sense desar un pes incorrecte.

### NFC / carnets

- Gravació d'una etiqueta NFC des de Chrome per a Android amb HTTPS; relectura amb el lector USB i amb el telèfon.
- Lector USB: prefix i terminador correctes a **Carnets i lectors**; lectura de codi de barres Code 128 impresa.
- Comprova que un UID de xip qualsevol **no** s'accepta com a carnet.

### Fallades i seguretat

- Atura el contenidor de BD: l'alerta de `/salut` arriba en ≤ 15 min i el servei es recupera en tornar-la a engegar.
- Fes fallar la còpia a propòsit (treu `CLUB_BACKUP_REMOTE`): ha de fallar amb missatge i amb alerta `OnFailure`.
- Intents de login erronis (5): bloqueig; `python -m app.cli desbloquejar`.
- Verifica que l'aplicació no exposa res fora de nginx/Tailscale (`ss -tlnp`: només 127.0.0.1:8099) i que `limit_req` retorna 429 a `/auth/`.
- Verificació de l'auditoria (`club-audit-verify.py`) i `systemd-analyze security`.

## Criteris per passar a producció

- [ ] Cap incidència bloquejant oberta; resta classificades.
- [ ] Una restauració completa feta des del **remot** amb el material de custòdia.
- [ ] Alertes rebudes al mòbil de la persona responsable.
- [ ] Bàscula WANT WT3002A validada amb captures, o decisió documentada de dispensar amb entrada manual.
- [ ] Documents RGPD (`docs/RGPD.md`) revisats per l'advocat/DPO.
- [ ] Es destrueix la BD del pilot (i les seves còpies).
