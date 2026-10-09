FROM nginx:alpine
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/nginx.conf
COPY app-locations.conf /etc/nginx/snippets/app-locations.conf
COPY site-http.conf site-tls.conf /etc/nginx/conditional/
COPY 40-select-tls.sh /docker-entrypoint.d/40-select-tls.sh
RUN chmod +x /docker-entrypoint.d/40-select-tls.sh
EXPOSE 80 443
