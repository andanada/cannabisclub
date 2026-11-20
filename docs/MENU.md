# Menú del club (TV i tauletes)

La carta es mostra a pantalles del club (TV o tauleta) i **surt sola de l'estoc**: el menú «Dispensari» mostra les genètiques amb estoc
i el «Bar» els productes no genètics. Noms, categories i preus (per gram o per unitat) són els del producte; si una genètica s'acaba
desapareix (o surt com a «Esgotat» si ho actives) i quan torna a haver-hi estoc, torna. Els trams de pes (1 g, 5 g, 10 g…) es calculen del preu actual.

## Com crear-lo
1. Menú lateral **Menú del club** (gerència, o treballadors amb el permís «Gestionar el menú del club…»). Ja hi ha un menú Dispensari i un Bar.
2. Es veu la vista prèvia ja feta, amb dades reals. Dos botons:
   - **Categories**: interruptors per triar quines categories es mostren, amb ordre (▲▼) i, si cal, amagar un producte concret.
   - **Disseny**: plantilla (Fosc, Negre, Clar, Crema, Nit), fons (color, degradat, imatge), logo, colors, mida de lletra, columnes, orientació, trams, segons per pàgina.
3. Els canvis es desen sols com a esborrany. **Publicar** els fa visibles a les pantalles.
4. «⋯» al costat dels menús: canviar nom, activar/desactivar, marcar per defecte, duplicar, esborrar o crear-ne un altre (opcional).

## Enllaçar una TV o una tauleta
- A **Pantalles** › **Nova pantalla**: nom, tipus i menú. Surt un enllaç secret `/pantalla/<codi>`.
- **Copiar enllaç** o **QR** i obre'l al navegador de la TV/tauleta (pantalla completa amb doble clic). No cal iniciar sessió.
- **TV**: rota sola les pàgines/columnes. **Tauleta**: es navega per categories i té cerca.
- La pantalla consulta cada 30 s i es refresca sola (preus, estoc, canvis publicats). Si cau la xarxa, manté l'última carta.
- **Revocar** talla l'accés a l'instant (l'enllaç passa a donar 404). Es pot canviar el menú d'una pantalla sense canviar-ne l'enllaç.

## Seguretat
- Les rutes `/pantalla/<codi>` són de només lectura i només mostren la carta (noms, categories, preus, disponibilitat); mai estoc exacte ni dades de socis.
- Sense codi, amb un codi inexistent o revocat, o des d'una IP fora de la xarxa del club: **404**. Límit de ritme per IP (`CLUB_PANTALLA_LIMIT`, per defecte 120 peticions/minut).
- Només s'accepten clients de xarxa privada (192.168/16, 10/8, 172.16/12), loopback o Tailscale (100.64/10). `CLUB_PANTALLES_IPS_LLIURES=1` ho desactiva (no recomanat). Darrere nginx cal `CLUB_TRUST_PROXY=1` perquè es vegi la IP real.
- El codi es desa com a hash i xifrat; el programa no el registra als seus logs (`/pantalla/***`). Compte: el registre d'accessos d'uvicorn/nginx sí que pot veure el camí; no el comparteixis.
- Auditoria: alta de pantalla, revocació, canvi de menú d'una pantalla, publicar, alta/duplicat/esborrat/canvis de menú. El desat automàtic de l'esborrany no s'audita.
- Les imatges (logo, fons) es redimensionen al navegador i es desen a la base de dades (màx. ~500 KB cadascuna).

## Nota legal
No exposis aquestes pantalles a Internet, a la via pública ni a un aparador visible des de l'exterior. El menú ha de quedar dins del local
i de la xarxa del club. Revisa amb l'advocat del club el contingut que es mostra (noms, preus, descripcions) i com es comunica dins del local.
