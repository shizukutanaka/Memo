#!/bin/bash
# Personal Memo System - Installation Script
# ===========================================

set -e

echo "================================================"
echo "個人用メモシステム インストーラー"
echo "Personal Memo System Installer"
echo "================================================"
echo ""

# Check Python version
echo "Checking Python version..."
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    echo "Please install Python 3.8 or higher"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo "✓ Found Python $PYTHON_VERSION"

# Check pip
echo "Checking pip..."
if ! command -v pip3 &> /dev/null; then
    echo "Error: pip is not installed"
    echo "Please install pip3"
    exit 1
fi
echo "✓ pip is available"

# Install dependencies
echo ""
echo "Installing dependencies..."
pip3 install cryptography>=41.0.0

echo ""
echo "✓ Dependencies installed successfully"

# Create data directory
echo ""
echo "Creating data directory..."
mkdir -p ~/.memo/credentials
mkdir -p ~/.memo/backups
chmod 700 ~/.memo
chmod 700 ~/.memo/credentials
chmod 700 ~/.memo/backups

echo "✓ Data directory created: ~/.memo/"

# Test installation
echo ""
echo "Testing installation..."
if python3 memo_personal.py add "インストールテスト" --no-encrypt > /dev/null 2>&1; then
    echo "✓ Installation test passed"
else
    echo "Warning: Test failed, but installation may still work"
fi

# Create alias helper
echo ""
echo "Creating alias helper..."
cat > ~/.memo/alias.sh << 'EOF'
# Memo System Aliases
alias memo='python3 /path/to/memo_personal.py'
alias memo-add='python3 /path/to/memo_personal.py add'
alias memo-list='python3 /path/to/memo_personal.py list'
alias memo-search='python3 /path/to/memo_personal.py search'
alias memo-backup='python3 /path/to/memo_personal.py backup'
alias memo-stats='python3 /path/to/memo_personal.py stats'
EOF

# Update path in alias.sh
CURRENT_DIR=$(pwd)
sed -i.bak "s|/path/to|$CURRENT_DIR|g" ~/.memo/alias.sh
rm -f ~/.memo/alias.sh.bak

echo "✓ Alias helper created: ~/.memo/alias.sh"

# Installation complete
echo ""
echo "================================================"
echo "✅ インストール完了！"
echo "✅ Installation Complete!"
echo "================================================"
echo ""
echo "次のステップ / Next Steps:"
echo ""
echo "1. エイリアスを有効化（オプション）:"
echo "   echo 'source ~/.memo/alias.sh' >> ~/.bashrc"
echo "   source ~/.bashrc"
echo ""
echo "2. 最初のメモを作成:"
echo "   python3 memo_personal.py add \"初めてのメモ\""
echo ""
echo "3. ヘルプを表示:"
echo "   python3 memo_personal.py --help"
echo ""
echo "4. クイックスタートガイドを読む:"
echo "   cat QUICKSTART.md"
echo ""
echo "⚠️  重要: 暗号化キーを必ずバックアップしてください！"
echo "   cp ~/.memo/credentials/memo_encryption.key <安全な場所>/"
echo ""
echo "================================================"
