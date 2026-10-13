#!/usr/bin/env bash
# Run in the existing Oracle checkout; retain data, settings and service definitions.
set -euo pipefail
repo=$(git rev-parse --show-toplevel)
cd "$repo"
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo 'DUR: Yerel değişiklikler var; hiçbir dosya sıfırlanmadı.' >&2
  exit 1
fi
if [[ -x .venv/bin/python ]]; then py=.venv/bin/python
elif [[ -x venv/bin/python ]]; then py=venv/bin/python
else py=python3; fi
# Identify existing active app units before changing code. Never invent a unit name.
units=()
while read -r unit rest; do
  [[ "$unit" == *.service ]] || continue
  work=$(systemctl show "$unit" -p WorkingDirectory --value)
  [[ "$work" == "$repo" ]] || continue
  command=$(systemctl show "$unit" -p ExecStart --value)
  [[ "$command" == *cloud_baslat.py* || "$command" == *ana_motor.py* || "$command" == *web_server.py* ]] || continue
  units+=("$unit")
done < <(systemctl list-units --type=service --state=running --no-legend --plain)
if (( ${#units[@]} == 0 || ${#units[@]} > 3 )); then
  echo 'DUR: Mevcut uygulama servisleri güvenle belirlenemedi; hiçbir servis değiştirilmedi.' >&2
  exit 1
fi
git fetch origin main
git merge --ff-only origin/main
"$py" -B -m unittest tests.test_price_freshness -q
sudo systemctl restart "${units[@]}"
for unit in "${units[@]}"; do systemctl is-active --quiet "$unit"; done
echo 'Uygulama servisleri aktif. Fiyatlar sağlayıcıdan sıradaki kapanış taramasında yenilenecek.'
