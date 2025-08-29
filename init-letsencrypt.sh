#!/bin/bash

if [ -f .env ]; then
  # Export only non-comment lines from .env file
  export $(grep -v '^#' .env | xargs)
fi

echo "Using domain: $SSL_DOMAIN"
echo "Using email: $SSL_EMAIL"

if [ -z "$SSL_DOMAIN" ] || [ -z "$SSL_EMAIL" ]; then
  echo "SSL_DOMAIN or SSL_EMAIL not set. Please check your .env file."
  exit 1
fi

echo "### Creating dummy certificate directory for $SSL_DOMAIN ..."
mkdir -p /home/markus/ti-monitoring/nginx/certbot-www/.well-known/acme-challenge/
mkdir -p /home/markus/ti-monitoring/nginx/certbot-conf/live/$SSL_DOMAIN/

echo "### Creating dummy certificate for $SSL_DOMAIN ..."
docker compose run --rm --entrypoint "\
  openssl req -x509 -nodes -newkey rsa:4096 -days 1\
    -keyout '/etc/letsencrypt/live/$SSL_DOMAIN/privkey.pem' \
    -out '/etc/letsencrypt/live/$SSL_DOMAIN/fullchain.pem' \
    -subj '/CN=localhost'" certbot
echo

echo "### Starting nginx ..."
# Process the template and start nginx
SSL_DOMAIN=$SSL_DOMAIN docker compose up --force-recreate -d nginx
echo

echo "### Deleting dummy certificate for $SSL_DOMAIN ..."
docker compose run --rm --entrypoint "\
  rm -Rf /etc/letsencrypt/live/$SSL_DOMAIN && \
  rm -Rf /etc/letsencrypt/archive/$SSL_DOMAIN && \
  rm -Rf /etc/letsencrypt/renewal/$SSL_DOMAIN.conf" certbot
echo

echo "### Requesting Let's Encrypt certificate for $SSL_DOMAIN ..."
# Join $SSL_DOMAIN to -d args as part of certbot command
docker compose run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    --email $SSL_EMAIL \
    -d $SSL_DOMAIN \
    --rsa-key-size 4096 \
    --agree-tos \
    --force-renewal" certbot
echo

echo "### Reloading nginx ..."
docker compose exec nginx nginx -s reload