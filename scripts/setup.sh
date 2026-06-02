#!/bin/bash
# Quick setup script

set -e

echo "Installing Python dependencies..."
pip install -r requirements.txt

echo "Installing Playwright browsers..."
playwright install chromium

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit config/companies.yaml — add your target companies"
echo "  2. Edit config/profile.yaml   — fill in your personal info"
echo "  3. Edit config/credentials.yaml — add LinkedIn/Indeed login + Anthropic API key"
echo "  4. Drop your resume PDF at: data/resume.pdf"
echo "  5. Run: python main.py discover"
echo "  6. Run: python main.py dashboard"
