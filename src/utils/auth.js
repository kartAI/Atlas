/**
 * Stores the session token and active chat ID in localStorage so state survives page refreshes.
 */

const TOKEN_KEY = "geo_auth_token";
const ACTIVE_CHAT_KEY = "geo_active_chat_id";

// Token management

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

// Active chat management

export function getActiveChatId() {
  return localStorage.getItem(ACTIVE_CHAT_KEY);
}

export function setActiveChatId(chatId) {
  if (chatId) {
    localStorage.setItem(ACTIVE_CHAT_KEY, chatId);
  } else {
    localStorage.removeItem(ACTIVE_CHAT_KEY);
  }
}

export function clearActiveChatId() {
  localStorage.removeItem(ACTIVE_CHAT_KEY);
}

// Authenticated fetch wrapper

/**
 * Wrapper around fetch() that automatically includes the Authorization header.
 *
 * @param {string} url
 * @param {RequestInit} [options]
 * @returns {Promise<Response>}
 */
export function apiFetch(url, options = {}) {
  const token = getToken();
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  return fetch(url, { ...options, headers });
}
