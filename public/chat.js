const form = document.getElementById('chat-form');
const userInput = document.getElementById('user-input');
const chatBox = document.getElementById('chat-box');
const typingIndicator = document.getElementById('typing-indicator');
const toggleDark = document.getElementById('toggle-dark');
const root = document.body;

// === Auto-scroll to latest message ===
function scrollToBottom() {
  chatBox.scrollTop = chatBox.scrollHeight;
}

// === Convert links into clickable hyperlinks ===
function linkify(text) {
  const urlPattern = /(https?:\/\/[^\s]+)/g;
  return text.replace(urlPattern, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
}

// === Append message bubble ===
function addMessage(content, sender = 'user') {
  const msg = document.createElement('div');
  msg.className = `message ${sender}`;

  const inner = document.createElement('div');
  inner.className = 'message-content';

  // Render hyperlinks in bot responses
  if (sender === 'bot') {
    inner.innerHTML = linkify(content);
  } else {
    inner.textContent = content;
  }

  msg.appendChild(inner);
  chatBox.appendChild(msg);
  scrollToBottom();
}

// === Initial bot greeting ===
window.addEventListener('DOMContentLoaded', () => {
  addMessage("Hello! I'm Cubie, your customer service assistant. How can I assist you today?", 'bot');

  // Load dark mode preference
  if (localStorage.getItem('cubie-theme') === 'dark') {
    root.classList.add('dark-mode');
    toggleDark.textContent = '☀️';
  }
});

// === Form submit handler ===
form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const question = userInput.value.trim();
  if (!question) return;

  addMessage(question, 'user');
  userInput.value = '';
  typingIndicator.style.display = 'flex';

  try {
    const response = await fetch('http://127.0.0.1:8000/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    });

    const data = await response.json();

    // Show GPT-generated reply
    if (data.reply) {
      addMessage(data.reply, 'bot');
    } else {
      addMessage("I'm not sure how to help with that. Try rephrasing your question.", 'bot');
    }
  } catch (err) {
    console.error("Error fetching response from backend:", err);
    addMessage("Oops! Something went wrong. Please try again later.", 'bot');
  } finally {
    typingIndicator.style.display = 'none';
  }
});

// === Allow Enter to submit, Shift+Enter for newline ===
userInput.addEventListener('keydown', function (e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault(); // Avoid new line
    form.dispatchEvent(new Event('submit'));
  }
});

// === Dark Mode Toggle ===
toggleDark.addEventListener('click', () => {
  root.classList.toggle('dark-mode');
  const isDark = root.classList.contains('dark-mode');
  toggleDark.textContent = isDark ? '☀️' : '🌙';
  localStorage.setItem('cubie-theme', isDark ? 'dark' : 'light');
});
