# Cámaras IP en directo (MikroTik + Tailscale)

El programa muestra en la pantalla **Cámaras** el vídeo en directo de las cámaras IP del club. Los navegadores no leen RTSP, así que el servidor del club
lanza `ffmpeg` por cada cámara que alguien está mirando, extrae fotogramas JPEG (~2 por segundo, 640 px) y los sirve con autenticación.
Cuando nadie mira una cámara durante 30 s, `ffmpeg` se detiene. No se graba nada: es solo directo.

## 1. En el servidor del club

    sudo apt install ffmpeg        # una vez
    sudo systemctl restart club-gestio

(sin `ffmpeg` la pantalla avisa «El servidor no tiene ffmpeg instalado»). Si está en otra ruta: variable `CLUB_FFMPEG=/ruta/ffmpeg`.

## 2. Que el servidor vea las cámaras

El servidor tiene que llegar por red a las cámaras (RTSP, normalmente puerto 554). **No abras puertos de las cámaras a Internet en el MikroTik.**
Opciones seguras:

- **Servidor dentro de la red local de las cámaras:** no hace falta nada más.
- **Servidor fuera (Tailscale):** instala Tailscale en un equipo de la red del club (o en el propio MikroTik si lo soporta) y anuncia la subred de las
  cámaras como *subnet router* (`tailscale up --advertise-routes=192.168.88.0/24`), y apruébala en el panel de Tailscale. El servidor del programa
  (con Tailscale) ya llega a `192.168.88.x`.
- **WireGuard entre el MikroTik y el servidor:** crea la interfaz WireGuard en RouterOS y una ruta hacia la red de las cámaras.

En el firewall del MikroTik, deja que solo el servidor (o la VPN) llegue al puerto 554 de las cámaras (regla `forward` con `src-address` del servidor
y `drop` para el resto). Si las cámaras están en su propia VLAN, mejor.

**Restricción de seguridad del programa:** solo acepta direcciones de red privada (192.168.x.x, 10.x.x.x, 172.16–31.x.x) o de Tailscale (100.64–127.x.x),
para que nadie pueda usar el servidor como puente hacia Internet. (`CLUB_CAMERES_HOSTS_LLIURES=1` lo desactiva: no recomendado.)

## 3. Dar de alta las cámaras

*Configuración › Cámaras* (solo administrador): nombre y dirección RTSP **con el usuario y la contraseña de la cámara**. La dirección se guarda
**cifrada** y no vuelve a mostrarse. Botón **Provar** comprueba que llega imagen. Direcciones típicas (cambian según modelo; usa un usuario de solo lectura):

| Marca | Dirección RTSP |
|---|---|
| Hikvision | `rtsp://usuario:clave@192.168.88.20:554/Streaming/Channels/102` (102 = flujo secundario, más ligero) |
| Dahua / Amcrest | `rtsp://usuario:clave@192.168.88.21:554/cam/realmonitor?channel=1&subtype=1` |
| Reolink | `rtsp://usuario:clave@192.168.88.22:554/h264Preview_01_sub` |
| TP-Link Tapo / Imou | `rtsp://usuario:clave@192.168.88.23:554/stream2` |
| Genérica ONVIF | `rtsp://usuario:clave@IP:554/` (consulta el manual o usa un visor ONVIF para ver la ruta) |

Usa siempre el **flujo secundario** (baja resolución): el programa lo reduce a 640 px y el servidor gasta menos CPU. Máximo 16 cámaras por local y 8 abiertas a la vez.
Para probar sin cámara: dirección `test://patro` (imagen sintética).

## 4. Quién las ve

Administrador y encargado, y los trabajadores a quienes el administrador dé el permiso **«Ver las cámaras en directo»** (Configuración › Usuarios). Abrir la pantalla
queda en el registro de auditoría. La URL con credenciales nunca llega al navegador ni a la auditoría.

## 5. Protección de datos (RGPD)

La videovigilancia es un tratamiento de datos personales con requisitos propios: **cartel informativo** visible en la zona vigilada, **responsable identificado**,
cámaras orientadas solo a lo necesario (no a zonas privadas ni a la vía pública), y registro en el registro de actividades. Este módulo solo muestra directo
(no graba); si se añaden grabaciones habrá que fijar un plazo de conservación (en España, como máximo 30 días en general) y quién puede verlas.
Valídalo con el abogado/DPO junto con el resto de `docs/REVISION_LEGAL.md`.
