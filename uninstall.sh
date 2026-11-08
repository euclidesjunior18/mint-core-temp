#!/usr/bin/env bash
set -e

APP_ID="mint-core-temp"

echo "=========================================================="
echo "    Desinstalando atalhos do Mint Core Temp"
echo "=========================================================="

rm -f "$HOME/.local/share/applications/${APP_ID}.desktop"
rm -f "$HOME/.config/autostart/${APP_ID}.desktop"
rm -f "$HOME/.local/share/icons/hicolor/scalable/apps/${APP_ID}.svg"
rm -f "$HOME/.local/share/icons/hicolor/128x128/apps/${APP_ID}.png"

if command -v update-desktop-database &> /dev/null; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi

echo "Atalhos e ícones removidos com sucesso."
echo "Os arquivos do programa em seu diretório continuam preservados."
