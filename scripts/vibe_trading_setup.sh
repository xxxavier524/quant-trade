#!/bin/bash
# Vibe-Trading setup script
set -e
VIBE_DIR="/Users/qiushixuan/cc/vibe-trading"
if [ -d "$VIBE_DIR" ]; then
    echo "Vibe-Trading already cloned, updating..."
    cd "$VIBE_DIR" && git pull
else
    echo "Cloning Vibe-Trading..."
    cd /Users/qiushixuan/cc
    git clone https://github.com/HKUDS/Vibe-Trading.git vibe-trading
    cd vibe-trading
    cp agent/.env.example agent/.env
    echo ""
    echo "Done! Next steps:"
    echo "1. Edit agent/.env with your DeepSeek API key"
    echo "2. Run: cd vibe-trading && docker compose up --build -d"
    echo "3. Verify: curl http://localhost:8899/health"
fi
