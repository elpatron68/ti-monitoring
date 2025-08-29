#!/bin/bash

if [ -f .env ]; then
  export $(cat .env | xargs)
fi

if [ -f config.yaml ]; then
  # Extract domain and email from config.yaml using Python
  export SSL_DOMAIN=$(python3 -c "import yaml; f=open('config.yaml'); c=yaml.safe_load(f); print(c.get('core', {}).get('ssl', {}).get('domain', ''))")
  export SSL_EMAIL=$(python3 -c "import yaml; f=open('config.yaml'); c=yaml.safe_load(f); print(c.get('core', {}).get('ssl', {}).get('email', ''))")
fi

echo "Using domain: $SSL_DOMAIN"
echo "Using email: $SSL_EMAIL"

if [ -z "$SSL_DOMAIN" ] || [ -z "$SSL_EMAIL" ]; then
  echo "SSL_DOMAIN or SSL_EMAIL not set. Please check your config.yaml or .env file."
  exit 1
fi

echo "### Creating dummy certificate for $SSL_DOMAIN ..."
docker-compose run --rm --entrypoint "\
  openssl req -x509 -nodes -newkey rsa:4096 -days 1\
    -keyout '/etc/letsencrypt/live/$SSL_DOMAIN/privkey.pem' \
    -out '/etc/letsencrypt/live/$SSL_DOMAIN/fullchain.pem' \
    -subj '/CN=localhost'" certbot
echo

echo "### Starting nginx ..."
docker-compose up --force-recreate -d nginx
echo

echo "### Deleting dummy certificate for $SSL_DOMAIN ..."
docker-compose run --rm --entrypoint "\
  rm -Rf /etc/letsencrypt/live/$SSL_DOMAIN && \
  rm -Rf /etc/letsencrypt/archive/$SSL_DOMAIN && \
  rm -Rf /etc/letsencrypt/renewal/$SSL_DOMAIN.conf" certbot
echo

echo "### Requesting Let's Encrypt certificate for $SSL_DOMAIN ..."
# Join $SSL_DOMAIN to -d args as part of certbot command
docker-compose run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    --email $SSL_EMAIL \
    -d $SSL_DOMAIN \
    --rsa-key-size 4096 \
    --agree-tos \
    --force-renewal" certbot
echo

echo "### Reloading nginx ..."
docker-compose exec nginx nginx -s reload