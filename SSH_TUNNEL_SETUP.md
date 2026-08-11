# SSH-Tunnel-Setup (Mac Pro)

Zugriff auf den Dienst auf Port 8765 des Zielrechners über einen lokalen SSH-Tunnel.

## Schritte

1. Am Mac Pro das Terminal öffnen und eingeben:

   ```bash
   ssh -N -L 8765:127.0.0.1:8765 d@xx.local
   ```

   Beim Verbinden das Passwort am Mac Pro eingeben (es wird das Passwort des Benutzers `d` auf dem Zielrechner `xx.local` abgefragt).

2. Solange der Befehl läuft, im Browser öffnen:

   http://localhost:8765

## Was der Befehl macht

- `-L 8765:127.0.0.1:8765` — leitet den lokalen Port 8765 durch den Tunnel an Port 8765 auf dem Zielrechner weiter (aus Sicht des Zielrechners: `127.0.0.1:8765`). So ist ein Dienst erreichbar, der auf dem Zielrechner nur lokal lauscht.
- `-N` — es wird keine Shell geöffnet, die Verbindung dient nur dem Tunnel. Das Terminalfenster bleibt scheinbar „hängen“ — das ist normal und bedeutet, dass der Tunnel steht.
- `d@xx.local` — Benutzer `d` auf dem Rechner `xx.local` (mDNS/Bonjour-Name im lokalen Netz).

## Tunnel beenden

Im Terminal `Ctrl+C` drücken oder das Terminalfenster schließen.

## Fehlerbehebung

- **`Could not resolve hostname xx.local`** — der Zielrechner ist nicht im selben Netz erreichbar oder der Bonjour-Name stimmt nicht. Alternativ die IP-Adresse des Zielrechners statt `xx.local` verwenden.
- **`bind: Address already in use`** — auf dem Mac Pro belegt bereits ein Prozess Port 8765. Entweder diesen Prozess beenden oder einen anderen lokalen Port wählen, z. B. `-L 9765:127.0.0.1:8765`, und dann http://localhost:9765 öffnen.
- **Browser zeigt „Verbindung abgelehnt“** — der Tunnel steht, aber auf dem Zielrechner läuft der Dienst auf Port 8765 gerade nicht. Dienst dort zuerst starten.
- **`Connection refused` beim SSH-Verbinden** — auf dem Zielrechner ist SSH nicht aktiviert (macOS: Systemeinstellungen → Allgemein → Teilen → „Entfernte Anmeldung“ einschalten).
