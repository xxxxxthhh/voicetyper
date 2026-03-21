#!/bin/bash
# VoiceTyper setup script for macOS
set -e

echo "🎙️  VoiceTyper Setup"
echo "===================="

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Install it first."
    exit 1
fi

# Check brew + portaudio
if ! command -v brew &> /dev/null; then
    echo "⚠️  Homebrew not found. Install portaudio manually if needed."
else
    if ! brew list portaudio &> /dev/null 2>&1; then
        echo "📦 Installing portaudio..."
        brew install portaudio
    else
        echo "✅ portaudio already installed"
    fi
fi

# Install Python deps
echo "📦 Installing Python dependencies..."
pip3 install -r requirements.txt

# Create data dir
mkdir -p ~/.voicetyper

# Check API key
if [ -z "$GROQ_API_KEY" ]; then
    echo ""
    echo "⚠️  GROQ_API_KEY not set. Add to your shell profile:"
    echo "   echo 'export GROQ_API_KEY=\"your-key\"' >> ~/.zshrc"
    echo ""
fi

echo ""
echo "✅ Setup complete! Run with:"
echo "   python3 run.py"
echo ""
echo "📌 Remember to grant Accessibility & Microphone permissions"
echo "   System Settings → Privacy & Security"
