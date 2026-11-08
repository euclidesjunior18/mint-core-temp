#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="mint-core-temp"

echo "=========================================================="
echo "      Instalando Mint Core Temp no Linux Mint"
echo "=========================================================="

# Tornar scripts executáveis
chmod +x "$DIR/core_temp.py"
[ -f "$DIR/uninstall.sh" ] && chmod +x "$DIR/uninstall.sh"

# Criar diretórios de ícones e aplicações do usuário
mkdir -p "$HOME/.local/share/applications"
mkdir -p "$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$HOME/.local/share/icons/hicolor/128x128/apps"

# Copiar ícones
echo "-> Instalando ícones do sistema..."
cp "$DIR/icon.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/${APP_ID}.svg"
cp "$DIR/icon.png" "$HOME/.local/share/icons/hicolor/128x128/apps/${APP_ID}.png"

# Criar arquivo de atalho no Menu de Aplicativos
echo "-> Criando lançador no menu do sistema..."
cat <<EOF > "$HOME/.local/share/applications/${APP_ID}.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=Mint Core Temp
GenericName=Monitor de Temperatura da CPU
Comment=Monitora a temperatura do processador na bandeja do sistema
Exec=$DIR/core_temp.py
Icon=$APP_ID
Terminal=false
Categories=System;Monitor;Utility;HardwareSettings;
Keywords=cpu;temperatura;coretemp;hardware;sensor;monitor;
StartupNotify=false
X-GNOME-Autostart-enabled=true
EOF

chmod +x "$HOME/.local/share/applications/${APP_ID}.desktop"

# Atualizar bancos de dados do sistema
if command -v update-desktop-database &> /dev/null; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi

if command -v gtk-update-icon-cache &> /dev/null; then
    gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
fi

echo "=========================================================="
echo " Instalação concluída com sucesso!"
echo " O aplicativo já aparece no menu do Linux Mint:"
echo " Menu -> Sistema ou pesquise por 'Mint Core Temp' / 'Temperatura'"
echo ""
echo " Para iniciar diretamente pelo terminal:"
echo "   $DIR/core_temp.py"
echo " Ou para iniciar direto minimizado na bandeja:"
echo "   $DIR/core_temp.py --minimized"
echo "=========================================================="
