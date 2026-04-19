#!/usr/bin/env bash
# One-shot setup for the macOS Chess bot.
set -euo pipefail

echo "==> Installing Stockfish..."
if command -v brew &>/dev/null; then
    brew install stockfish
elif command -v apt-get &>/dev/null; then
    sudo apt-get install -y stockfish
else
    echo "ERROR: Could not find brew or apt-get."
    echo "Download Stockfish manually from https://stockfishchess.org/download/"
    exit 1
fi

echo "==> Installing Python dependencies..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

echo ""
echo "Setup complete.  Run the bot with:"
echo "  python3 chess_bot.py --help"
