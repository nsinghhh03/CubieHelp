const form = document.getElementById('chat-form');
const userInput = document.getElementById('user-input');
const chatBox = document.getElementById('chat-box');
const typingIndicator = document.getElementById('typing-indicator');
const toggleDark = document.getElementById('toggle-dark');
const micButton = document.getElementById('mic-button');
const root = document.body;

let isRecording = false;
let recognition;

function scrollToBottom() {
  chatBox.scrollTop = chatBox.scrollHeight;
}

async function typeText(container, text) {
  container.innerHTML = '';
  const temp = document.createElement('div');
  temp.innerHTML = marked.parse(text, { breaks: true, gfm: true });
  const fullHTML = temp.innerHTML;
  let i = 0;
  function type() {
    if (i <= fullHTML.length) {
      container.innerHTML = fullHTML.slice(0, i++);
      scrollToBottom();
      setTimeout(type, 8);
    }
  }
  type();
}

function addMessage(content, sender = 'user', slowType = false) {
  const msg = document.createElement('div');
  msg.className = `message ${sender}`;
  const inner = document.createElement('div');
  inner.className = 'message-content';
  msg.appendChild(inner);
  chatBox.appendChild(msg);
  scrollToBottom();

  if (sender === 'bot' && slowType) {
    typeText(inner, content);
  } else if (sender === 'bot') {
    inner.innerHTML = marked.parse(content, { breaks: true, gfm: true });
  } else {
    inner.textContent = content;
  }
}

window.addEventListener('DOMContentLoaded', () => {
  addMessage("Hello! I'm Cubie, your customer service assistant. How can I assist you today?", 'bot');
  if (localStorage.getItem('cubie-theme') === 'dark') {
    root.classList.add('dark-mode');
    toggleDark.textContent = '☀️';
  }
});

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const question = userInput.value.trim();
  if (!question) return;

  addMessage(question, 'user');
  userInput.value = '';
  typingIndicator.style.display = 'flex';

  try {
    const response = await fetch('https://cubiehelp.onrender.com/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    });

    const data = await response.json();
    if (data.reply) {
      addMessage(data.reply, 'bot', true);
    } else {
      addMessage("I'm not sure how to help with that. Try rephrasing your question.", 'bot');
    }
  } catch (err) {
    console.error("Backend error:", err);
    addMessage("Oops! Something went wrong. Please try again later.", 'bot');
  } finally {
    typingIndicator.style.display = 'none';
  }
});

userInput.addEventListener('keydown', function (e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    form.dispatchEvent(new Event('submit'));
  }
});

toggleDark.addEventListener('click', () => {
  root.classList.toggle('dark-mode');
  const isDark = root.classList.contains('dark-mode');
  toggleDark.textContent = isDark ? '☀️' : '🌙';
  localStorage.setItem('cubie-theme', isDark ? 'dark' : 'light');
});

// === Voice to Text Manual Toggle ===
if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRecognition();
  recognition.lang = 'en-US';
  recognition.continuous = false;
  recognition.interimResults = false;

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    userInput.value = transcript;
    micButton.textContent = '🎤';
    isRecording = false;
  };

  recognition.onerror = (event) => {
    console.error('Speech recognition error:', event.error);
    micButton.textContent = '🎤';
    isRecording = false;
  };

  recognition.onend = () => {
    micButton.textContent = '🎤';
    isRecording = false;
  };

  micButton.addEventListener('click', () => {
    if (!isRecording) {
      recognition.start();
      micButton.textContent = '🛑 Stop';
      isRecording = true;
    } else {
      recognition.stop();
      micButton.textContent = '🎤';
      isRecording = false;
    }
  });
} else {
  console.warn("Speech recognition not supported in this browser.");
  micButton.style.display = 'none';
}