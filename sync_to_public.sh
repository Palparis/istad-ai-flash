#!/bin/bash
# sync_to_public.sh - Synchronise agent-audit-flash/ vers le repo public istad-ai-flash
#
# Usage :
#     ./sync_to_public.sh "message de commit"
#     ./sync_to_public.sh             # message par défaut "sync from monorepo"
#
# Le script :
# 1. Clone le repo public istad-ai-flash en local s'il n'existe pas encore
# 2. Synchronise tous les fichiers du sous-projet
# 3. Commit + push automatique vers GitHub
# 4. Streamlit Cloud redéploie automatiquement (~1-2 min)

set -e  # arrêt immédiat sur erreur

MSG="${1:-sync from monorepo}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUBLIC_DIR="$HOME/istad-ai-flash-public"  # hors Dropbox pour éviter conflits sync

echo "▸ Source     : $SRC_DIR"
echo "▸ Destination: $PUBLIC_DIR"

# 1. Cloner le repo public si nécessaire
if [ ! -d "$PUBLIC_DIR/.git" ]; then
    echo ""
    echo "▸ Premier run - clonage de Palparis/istad-ai-flash dans $PUBLIC_DIR"
    git clone https://github.com/Palparis/istad-ai-flash.git "$PUBLIC_DIR"
fi

# 2. Synchroniser les fichiers (exclusions : .git, caches Python, OS files, sessions)
echo ""
echo "▸ Synchronisation des fichiers…"
rsync -av --delete \
    --exclude='.git/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.DS_Store' \
    --exclude='sessions/' \
    --exclude='.venv/' \
    "$SRC_DIR/" "$PUBLIC_DIR/"

# 3. Commit + push
cd "$PUBLIC_DIR"
git add -A

if git diff --staged --quiet; then
    echo ""
    echo "✓ Aucun changement à pousser. Repo public déjà à jour."
    exit 0
fi

echo ""
echo "▸ Commit & push…"
git commit -m "$MSG"
git push

echo ""
echo "✓ Pushé sur Palparis/istad-ai-flash."
echo "✓ Streamlit Cloud va redéployer automatiquement dans ~1-2 min."
echo "✓ Ton URL : https://istad-ai-flash.streamlit.app"
