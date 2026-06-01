#!/bin/bash
set -e

echo "=== MLB Analytics Platform Setup ==="

# Backend
echo ""
echo "→ Setting up Python backend..."
cd backend
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "  Created backend/.env — fill in your API keys before running"
fi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
echo "  Backend dependencies installed"
cd ..

# Frontend
echo ""
echo "→ Setting up frontend..."
cd frontend
npm install
echo "  Frontend dependencies installed"
cd ..

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit backend/.env and add your SPORTRADAR_API_KEY and ANTHROPIC_API_KEY"
echo "  2. Start Postgres + Redis:  docker-compose up postgres redis -d"
echo "  3. Seed MLB rosters:        cd backend && source .venv/bin/activate && python -m scripts.ingest --season 2024"
echo "  4. Seed minor leagues:      python -m scripts.ingest_minors --season 2024"
echo "  5. Start backend:           uvicorn app.main:app --reload"
echo "  6. Start frontend:          cd ../frontend && npm run dev"
echo ""
echo "  Or run everything with Docker:  docker-compose up"
echo ""
echo "MLB ingest flags (requires Sportradar key):"
echo "  --season 2024          one season"
echo "  --season 2023 2024     multiple seasons"
echo "  --team NYY             one team only (fast, good for testing)"
echo "  --dry-run              preview without writing to the database"
echo ""
echo "MiLB ingest flags (free — no key required):"
echo "  --season 2024"
echo "  --level AAA AA         specific levels (AAA AA A+ A Rookie)"
echo "  --affiliate NYY        one MLB org's farm system only"
echo "  --dry-run"
echo ""
echo "API docs:  http://localhost:8000/docs"
echo "App:       http://localhost:3000"
