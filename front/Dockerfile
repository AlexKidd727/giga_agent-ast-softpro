# 1) Сборка приложения
FROM node:22.12.0-alpine AS builder
WORKDIR /app

# устанавливаем зависимости
COPY package.json package-lock.json* ./
RUN npm install

# копируем исходники и билдим
COPY . .
RUN npm run build

# 2) Nginx для отдачи статики
FROM nginx:alpine

# копируем сгенерированные файлы
COPY --from=builder /app/dist /usr/share/nginx/html
# копируем свою конфигурацию nginx
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]