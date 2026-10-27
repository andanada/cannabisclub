# Requisits funcionals — club-gestio

Programa propi de gestió d'un club. Els requisits descriuen QUÈ ha de fer; el disseny, el codi i els textos són originals.
Font dels requisits: les funcions que el sector anuncia públicament i les necessitats del club.

## 1. Socis
- Alta de soci en pocs segons, sense paper: dades personals, document d'identitat, foto opcional, data d'alta.
- Signatura electrònica de l'alta (pad de signatura o pantalla tàctil) amb constància de data i hora.
- Validació de dades (format de document, majoria d'edat, duplicats).
- Estat del soci (actiu, suspès, baixa) i historial de canvis.
- Identificació ràpida: cerca per nom/document i lectura de carnet RFID o codi.
- Registre d'entrades (check-in) del soci.

## 2. Estoc i dispensacions
- Catàleg de productes, categories i preus.
- Entrades d'estoc (compra, collita, ajust) i sortides (dispensació, merma).
- Pesatge connectat a bàscula per a la dispensació, amb el pes registrat al moviment.
- Cada moviment queda registrat amb traçabilitat completa: qui, quan, quant i a qui.
- Els moviments no es poden editar ni esborrar: només es corregeixen amb un moviment de contrapartida.
- Límits configurables per soci i període.

## 3. Caixa
- Cobraments associats a una dispensació o a una quota.
- Obertura i tancament de caixa, amb quadrament i diferències.
- Despeses: crear, consultar i veure'n l'historial.
- Informe de caixa per dia, setmana i mes.

## 4. Personal
- Fitxatge d'entrada, sortida i pauses.
- Total d'hores treballades per persona i període.
- Usuaris amb rols i permisos (administrador, encarregat, dispensador).

## 5. Multi-local
- Diversos locals dins d'una mateixa instal·lació, cadascun amb la seva caixa, estoc, despeses i personal.
- Permisos per usuari i per local.

## 6. Informes
- Resum d'activitat, estoc actual i valorat, vendes, caixa, assistència de personal.
- Exportació a CSV.

## 7. Seguretat i traçabilitat (requisits no funcionals)
- Dades personals xifrades en repòs a nivell de camp.
- Autenticació amb contrasenya robusta i segon factor (TOTP).
- Registre d'auditoria només d'afegir, amb hash encadenat, verificable.
- Registre d'accessos a dades de socis.
- Còpies de seguretat xifrades i prova de restauració.
- Accés només per xarxa privada (Tailscale); mai exposat a Internet.

## 8. Fora d'abast per ara
- Maquinari concret (bàscula, lector RFID, pad de signatura): es defineix quan se'n triï el model.
- Aplicació mòbil nativa: s'usa una PWA.
