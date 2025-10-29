import 'dotenv/config';

console.log('WP Lead Magnet Inserter запущен!');

const requiredEnv = ['WORDPRESS_API_URL', 'WORDPRESS_USERNAME', 'WORDPRESS_PASSWORD', 'OPENAI_API_KEY'];
const missing = requiredEnv.filter((key) => !process.env[key]);

if (missing.length) {
  console.error('Отсутствуют переменные окружения:', missing.join(', '));
  process.exit(1);
}

console.log('Все необходимые переменные окружения присутствуют.');
