const form = document.getElementById('chat-form');
const userInput = document.getElementById('user-input');
const chatBox = document.getElementById('chat-box');
const typingIndicator = document.getElementById('typing-indicator');
const toggleDark = document.getElementById('toggle-dark');
const micButton = document.getElementById('mic-button');
const root = document.body;

let isRecording = false;
let recognition;

// SVG constants for copy button (user provided, no border, no fill)
const COPY_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8"><rect x="9" y="9" width="11" height="11" rx="2" ry="2"></rect><path d="M15 9V7a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"></path></svg>`;
const COPIED_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><polyline points="5 13 9 17 19 7" /></svg>`;

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

function createCopyButton(inner) {
  const btn = document.createElement('button');
  btn.className = 'copy-btn-right';
  btn.title = 'Copy to clipboard';
  btn.innerHTML = COPY_SVG;
  btn.onclick = function () {
    navigator.clipboard.writeText(inner.textContent.trim());
    btn.innerHTML = COPIED_SVG;
    setTimeout(() => { btn.innerHTML = COPY_SVG; }, 1200);
  };
  return btn;
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

  if (sender === 'bot') {
    const copyWrapper = document.createElement('div');
    copyWrapper.className = 'copy-btn-right-wrapper';
    copyWrapper.appendChild(createCopyButton(inner));
    // Place the copy button wrapper as a child of the message bubble for absolute positioning
    msg.appendChild(copyWrapper);
  }
}

window.addEventListener('DOMContentLoaded', () => {
  // Typewriter effect for initial message
  const prefs = getCubiePrefs();
  const initialMsg = prefs.name
    ? `Hello ${prefs.name}! I'm Cubie, your customer service assistant. How can I assist you today?`
    : "Hello! I'm Cubie, your customer service assistant. How can I assist you today?";
  function typeInitialMessage(msg, cb) {
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message bot';
    const inner = document.createElement('div');
    inner.className = 'message-content';
    msgDiv.appendChild(inner);
    chatBox.appendChild(msgDiv);
    let i = 0;
    function type() {
      if (i <= msg.length) {
        inner.textContent = msg.slice(0, i++);
        scrollToBottom();
        setTimeout(type, 18);
      } else {
        if (cb) cb(msgDiv);
      }
    }
    type();
  }
  // Remove any existing suggestion bubbles
  let oldBubbles = document.getElementById('suggestion-bubbles');
  if (oldBubbles) oldBubbles.remove();
  // Type initial message, then show suggestion bubbles right after it
  typeInitialMessage(initialMsg, (msgDiv) => {
    setTimeout(() => {
      // Create and insert suggestion bubbles after the first message
      const suggestionBubbles = document.createElement('div');
      suggestionBubbles.className = 'suggestion-bubbles';
      suggestionBubbles.id = 'suggestion-bubbles';
      suggestionBubbles.innerHTML = `
        <button class="suggestion-btn">Application Help</button>
        <button class="suggestion-btn">Analyze Data</button>
        <button class="suggestion-btn">Visualize Data</button>
      `;
      msgDiv.after(suggestionBubbles);
      setTimeout(() => {
        suggestionBubbles.classList.add('visible');
      }, 50);
      // Suggestion bubble click handler
      suggestionBubbles.addEventListener('click', function(e) {
        if (e.target.classList.contains('suggestion-btn')) {
          const text = e.target.textContent.trim();
          userInput.value = text;
          form.dispatchEvent(new Event('submit'));
          // Remove focus to prevent border from staying
          e.target.blur();
        }
      });
    }, 400);
  });
  if (localStorage.getItem('cubie-theme') === 'dark') {
    root.classList.add('dark-mode');
    toggleDark.textContent = '☀️';
  }
  const downloadBtn = document.getElementById('download-pdf');
  if (downloadBtn) {
    downloadBtn.addEventListener('click', function () {
      const messages = Array.from(document.querySelectorAll('.message'));
      let text = '';
      messages.forEach(msg => {
        if (msg.classList.contains('user')) {
          text += 'You: ';
        } else {
          text += 'Cubie: ';
        }
        text += msg.textContent.trim() + '\n\n';
      });
      const { jsPDF } = window.jspdf;
      const doc = new jsPDF({ unit: 'pt', format: 'a4' });
      const margin = 40;
      let y = margin + 30;
      doc.setFont('helvetica', 'bold');
      doc.setFontSize(18);
      doc.text('Cubie Conversation', margin, margin);
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(12);
      const now = new Date();
      const dateStr = now.toLocaleString();
      doc.text('Date: ' + dateStr, margin, margin + 18);
      doc.setLineWidth(0.5);
      doc.line(margin, margin + 24, 555, margin + 24);
      y = margin + 40;
      const lines = doc.splitTextToSize(text, 515 - margin * 2);
      lines.forEach(line => {
        if (y > 780) {
          doc.addPage();
          y = margin;
        }
        doc.text(line, margin, y);
        y += 18;
      });
      doc.save('Cubie_Conversation.pdf');
    });
  }
});

// === Customize Modal Logic ===
const customizeBtn = document.getElementById('customize-btn');
const customizeModal = document.getElementById('customize-modal');
const closeCustomize = document.getElementById('close-customize');
const customizeCancel = document.getElementById('customize-cancel');
const customizeForm = document.getElementById('customize-form');
const cubieNameInput = document.getElementById('cubie-name');

function getCubiePrefs() {
  try {
    return JSON.parse(localStorage.getItem('cubiePrefs')) || {};
  } catch (e) {
    return {};
  }
}

function setCubiePrefs(prefs) {
  localStorage.setItem('cubiePrefs', JSON.stringify(prefs));
}

function openCustomizeModal() {
  customizeModal.style.display = 'flex';
  // Load preferences from localStorage
  const prefs = getCubiePrefs();
  cubieNameInput.value = prefs.name || '';
  // Set response length
  document.querySelectorAll('.response-length-btn').forEach(btn => {
    btn.classList.toggle('selected', btn.dataset.length === prefs.length);
  });
  // Set traits
  document.querySelectorAll('.trait-btn').forEach(btn => {
    btn.classList.toggle('selected', (prefs.traits || []).includes(btn.dataset.trait));
  });
}
function closeCustomizeModal() {
  customizeModal.style.display = 'none';
}
if (customizeBtn) customizeBtn.onclick = openCustomizeModal;
if (closeCustomize) closeCustomize.onclick = closeCustomizeModal;
if (customizeCancel) customizeCancel.onclick = closeCustomizeModal;
// Response length single select
customizeModal && customizeModal.addEventListener('click', function(e) {
  if (e.target.classList.contains('response-length-btn')) {
    document.querySelectorAll('.response-length-btn').forEach(btn => btn.classList.remove('selected'));
    e.target.classList.add('selected');
  }
  // Multi-select for traits
  if (e.target.classList.contains('trait-btn')) {
    e.target.classList.toggle('selected');
  }
});
// Save preferences
if (customizeForm) customizeForm.onsubmit = function(e) {
  e.preventDefault();
  const name = cubieNameInput.value.trim();
  const lengthBtn = document.querySelector('.response-length-btn.selected');
  const length = lengthBtn ? lengthBtn.dataset.length : '';
  const traits = Array.from(document.querySelectorAll('.trait-btn.selected')).map(btn => btn.dataset.trait);
  setCubiePrefs({ name, length, traits });
  closeCustomizeModal();
  // Reload the page to update the initial greeting
  window.location.reload();
};

// Use preferences in next message
// On page load, always load prefs and use for greeting
let cubiePrefs = getCubiePrefs();

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  // Always reload prefs in case they changed
  cubiePrefs = getCubiePrefs();
  const question = userInput.value.trim();
  if (!question) return;
  addMessage(question, 'user');
  userInput.value = '';
  typingIndicator.style.display = 'flex';
  try {
    const response = await fetch('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, prefs: cubiePrefs }),
    });
    const data = await response.json();
    if (data.reply) {
      // If user says hi cubie, use preferred name
      if (/^hi\s*cubie/i.test(question) && cubiePrefs.name) {
        addMessage(`Hi ${cubiePrefs.name}!`, 'bot', false);
      } else {
        addMessage(data.reply, 'bot', true);
      }
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