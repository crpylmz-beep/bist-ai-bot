"""Windows: py vapid_uret.py. Keys are displayed only; no files are written."""
import argparse
import base64
from urllib.parse import urlsplit


def validate_subject(subject):
    subject = subject.strip()
    if '@' in subject and '://' not in subject and not subject.startswith('mailto:'):
        subject = 'mailto:' + subject
    parsed = urlsplit(subject)
    if any(character.isspace() for character in subject):
        raise ValueError('Gecerli e-posta veya HTTPS iletisim adresi girin.')
    if parsed.scheme == 'mailto' and not parsed.query and not parsed.fragment:
        address = parsed.path
        if address.count('@') == 1 and all(address.split('@')):
            return subject
    if parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password:
        return subject
    raise ValueError('Gecerli e-posta veya HTTPS iletisim adresi girin.')


def generate(subject):
    """RAW 32-byte private key: directly accepted by pywebpush/py-vapid."""
    subject = validate_subject(subject)
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        raise RuntimeError('Once su komutu calistirin: py -m pip install -r requirements.txt') from None
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')
    return {
        'VAPID_PUBLIC_KEY': encode(public),
        'VAPID_PRIVATE_KEY': encode(private.private_numbers().private_value.to_bytes(32, 'big')),
        'VAPID_SUBJECT': subject,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--subject', help='Iletisim e-postasi, mailto: adresi veya HTTPS URL')
    args = parser.parse_args(argv)
    try:
        subject = args.subject or input('Iletisim e-posta adresiniz (VAPID_SUBJECT): ')
        values = generate(subject)
    except (ValueError, RuntimeError, EOFError) as error:
        parser.exit(1, str(error) + '\n')
    print('\nBu degerleri Railway Variables alanina ayri ayri kopyalayin.')
    print('Private key gizlidir. Chat/Git/log ile paylasmayin; dosyaya kaydedilmedi.')
    print('Ayni anahtarlari sonraki deploymentlarda koruyun.\n')
    for name, value in values.items():
        print(name + '=' + value)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
