#!/bin/bash
echo "Preparing deployment for Wasmer Edge..."

# Install all requirements locally into a vendor folder
pip install -r requirements.txt -t packages/

echo "✅ Dependencies bundled."
echo "Now run: wasmer deploy"
