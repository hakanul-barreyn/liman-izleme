#!/usr/bin/env bash
# Liman İzleme – Ubuntu sunucu kurulumu (Google Cloud e2-micro için hazırlandı)
# Kullanım (sunucunun SSH penceresinde tek satır):
#   curl -fsSL https://raw.githubusercontent.com/hakanul-barreyn/liman-izleme/main/kurulum/kur.sh | bash
set -euo pipefail

REPO_SSH="git@github.com:hakanul-barreyn/liman-izleme.git"
REPO_HTTPS="https://github.com/hakanul-barreyn/liman-izleme.git"
DIR="$HOME/liman-izleme"
say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ask() { local v; read -r -p "$1" v < /dev/tty; printf '%s' "$v"; }

say "1/7 Sistem paketleri kuruluyor"
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv python3-pip git openssh-client >/dev/null

say "2/7 Bellek için 1 GB takas alanı (küçük sunucuda gerekli)"
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

say "3/7 GitHub'a yazma anahtarı (deploy key)"
KEY="$HOME/.ssh/liman_izleme"
if [ ! -f "$KEY" ]; then
  mkdir -p "$HOME/.ssh" && ssh-keygen -t ed25519 -N "" -C "liman-izleme-sunucu" -f "$KEY" >/dev/null
fi
cat > "$HOME/.ssh/config" <<EOF
Host github.com
  IdentityFile $KEY
  IdentitiesOnly yes
  StrictHostKeyChecking accept-new
EOF
chmod 600 "$HOME/.ssh/config"
echo
echo "Aşağıdaki satırın TAMAMINI kopyala:"
echo
cat "$KEY.pub"
echo
echo "GitHub'da: depo → Settings → Deploy keys → Add deploy key"
echo "  Title: sunucu   Key: (yapıştır)   'Allow write access' kutusunu İŞARETLE → Add key"
ask "Ekledikten sonra Enter'a bas… " >/dev/null
until ssh -T git@github.com 2>&1 | grep -q "successfully authenticated"; do
  ask "GitHub anahtarı henüz kabul etmedi. Ekleyip tekrar Enter'a bas… " >/dev/null
done

say "4/7 Kod indiriliyor"
if [ ! -d "$DIR/.git" ]; then
  git clone "$REPO_SSH" "$DIR" || git clone "$REPO_HTTPS" "$DIR"
fi
cd "$DIR"
git remote set-url origin "$REPO_SSH"
git config user.name "liman-izleme-sunucu"
git config user.email "sunucu@liman-izleme.invalid"
git pull --rebase --autostash || true

say "5/7 Python ortamı kuruluyor (birkaç dakika sürebilir)"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

say "6/7 Gizli anahtarlar (.env dosyası, GitHub'a gitmez)"
if [ ! -f .env ] || ! grep -q AISSTREAM_API_KEY .env; then
  K=$(ask "aisstream.io API anahtarını yapıştır ve Enter'a bas: ")
  printf 'AISSTREAM_API_KEY=%s\n' "$K" > .env
  chmod 600 .env
fi

say "7/7 7/24 çalışan servis kuruluyor"
sudo tee /etc/systemd/system/liman.service >/dev/null <<EOF
[Unit]
Description=Liman Izleme
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/python -m liman calistir
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable liman >/dev/null

sudo systemctl restart liman
say "Kurulum tamam. Servis çalışıyor."
.venv/bin/python -m liman kontrol || echo "(Limanlar henüz yok: GitHub'da config.yaml'ı doldurduğunda sunucu 5 dakika içinde kendiliğinden başlar.)"
echo
echo "Durumu görmek için:     sudo systemctl status liman"
echo "Kayıtları izlemek için: journalctl -u liman -f"
