import axios from 'axios';

const WP_BASE_URL = process.env.WP_BASE_URL;
const WP_USER = process.env.WP_USER;
const WP_APP_PASSWORD = process.env.WP_APP_PASSWORD;

if (!WP_BASE_URL || !WP_USER || !WP_APP_PASSWORD) {
  throw new Error('WP_BASE_URL, WP_USER, WP_APP_PASSWORD должны быть заданы в .env');
}

const api = axios.create({
  baseURL: WP_BASE_URL.replace(/\/$/, '') + '/wp-json/wp/v2/',
  auth: {
    username: WP_USER,
    password: WP_APP_PASSWORD,
  },
});

export async function getPost(id: number) {
  const { data } = await api.get(`posts/${id}`);
  return data;
}

export async function listPosts(params: any = {}) {
  // params: { per_page, page, ... }
  const { data } = await api.get('posts', { params });
  return data;
}

export async function updatePostContent(id: number, content: string) {
  const { data } = await api.post(`posts/${id}`, { content });
  return data;
}
