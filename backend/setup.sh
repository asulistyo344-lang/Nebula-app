#!/bin/bash
# Nebula Backend Setup Script
# Works for both localhost (dev) and VPS (prod)

set -e
echo "🌌 Setting up Nebula backend..."

# ── Python deps ──────────────────────────────────────────────────
echo "Installing Python dependencies..."
pip install -r requirements.txt

# ── PostgreSQL ───────────────────────────────────────────────────
echo "Creating PostgreSQL database..."
sudo -u postgres psql -c "CREATE USER nebula WITH PASSWORD 'nebula_pass';" 2>/dev/null || true
sudo -u postgres psql -c "CREATE DATABASE nebula_db OWNER nebula;" 2>/dev/null || true
echo "✅ PostgreSQL ready"

# ── Redis ────────────────────────────────────────────────────────
echo "Checking Redis..."
redis-cli ping || (echo "❌ Redis not running - start it first" && exit 1)
echo "✅ Redis ready"

# ── .env file ────────────────────────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
  echo ""
  echo "⚠️  Created .env from template."
  echo "    Edit .env and set:"
  echo "    - DATABASE_URL (update password if changed)"
  echo "    - JWT_SECRET (change to a random string)"
  echo "    - FIREBASE_CREDENTIALS_PATH (after Firebase setup)"
  echo ""
fi

echo "🚀 Setup complete!"
echo ""
echo "To start (development):"
echo "  python main.py"
echo ""
echo "To start (production with PM2):"
echo "  pm2 start 'uvicorn main:app --host 0.0.0.0 --port 8000' --name nebula-api"
