const form = document.getElementById('chat-form');
const userInput = document.getElementById('user-input');
const chatBox = document.getElementById('chat-box');
const typingIndicator = document.getElementById('typing-indicator');
const toggleDark = document.getElementById('toggle-dark');
const micButton = document.getElementById('mic-button');
const notesBtn = document.getElementById('notes-btn');
const notesModal = document.getElementById('notes-modal');
const closeNotesBtn = document.getElementById('close-notes');
const notesList = document.getElementById('notes-list');
const notesEmpty = document.getElementById('notes-empty');
const root = document.body;

let isRecording = false;
let recognition;

// Track current conversation mode: "help" (default) or "analytics"
let currentMode = 'help';

// === Backend API URL ===
// Local dev uses same origin
const API_URL = '/api/query';

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
  const buttonContainer = document.createElement('div');
  buttonContainer.className = 'message-buttons';
  
  const copyBtn = document.createElement('button');
  copyBtn.className = 'copy-btn-right';
  copyBtn.title = 'Copy to clipboard';
  copyBtn.innerHTML = COPY_SVG;
  copyBtn.onclick = function () {
    navigator.clipboard.writeText(inner.textContent.trim());
    copyBtn.innerHTML = COPIED_SVG;
    setTimeout(() => { copyBtn.innerHTML = COPY_SVG; }, 1200);
  };
  
  const saveBtn = document.createElement('button');
  saveBtn.className = 'save-btn-right';
  saveBtn.title = 'Save to notes';
  saveBtn.innerHTML = `
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <polyline points="14,2 14,8 20,8"/>
      <line x1="16" y1="13" x2="8" y2="13"/>
      <line x1="16" y1="17" x2="8" y2="17"/>
      <polyline points="10,9 9,9 8,9"/>
    </svg>
  `;
  saveBtn.onclick = function () {
    addNote(inner.textContent.trim());
    updateNotesDisplay();
    saveBtn.innerHTML = `
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M9 12l2 2 4-4"/>
        <circle cx="12" cy="12" r="10"/>
      </svg>
    `;
    setTimeout(() => { 
      saveBtn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14,2 14,8 20,8"/>
          <line x1="16" y1="13" x2="8" y2="13"/>
          <line x1="16" y1="17" x2="8" y2="17"/>
          <polyline points="10,9 9,9 8,9"/>
        </svg>
      `;
    }, 1200);
  };
  
  buttonContainer.appendChild(copyBtn);
  buttonContainer.appendChild(saveBtn);
  return buttonContainer;
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
    
    // Check if this is an email draft and add approve button
    if (content.includes('📧 **Email Draft Ready for Approval**')) {
      const approveButton = document.createElement('button');
      approveButton.className = 'approve-email-btn';
      approveButton.textContent = '✅ Approve & Send Email';
      approveButton.onclick = async function() {
        approveButton.disabled = true;
        approveButton.textContent = '⏳ Sending...';
        
        try {
          // Build conversation history from current messages
          const messages = Array.from(document.querySelectorAll('.message'));
          const history = [];
          
          messages.forEach(msg => {
            if (msg.classList.contains('user')) {
              history.push({ role: 'user', content: msg.textContent.trim() });
            } else if (msg.classList.contains('bot')) {
              history.push({ role: 'assistant', content: msg.textContent.trim() });
            }
          });
          
          // Send approval directly to backend without going through AI
          const response = await fetch('/api/approve-email', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
              session_id: 'default' // Use the same session ID as the draft
            }),
          });
          const data = await response.json();
          if (data.reply) {
            // Only show the reply if it's not a generic greeting
            if (!data.reply.includes("I'm here to assist") && !data.reply.includes("How can I help")) {
              addMessage(data.reply, 'bot', true);
            }
            approveButton.textContent = '✅ Email Sent!';
            approveButton.style.background = '#28a745';
          } else {
            addMessage("Error sending email. Please try again.", 'bot');
            approveButton.disabled = false;
            approveButton.textContent = '✅ Approve & Send Email';
          }
        } catch (error) {
          addMessage("Error sending email. Please try again.", 'bot');
          approveButton.disabled = false;
          approveButton.textContent = '✅ Approve & Send Email';
        }
      };
      
      const approveWrapper = document.createElement('div');
      approveWrapper.className = 'approve-btn-wrapper';
      approveWrapper.appendChild(approveButton);
      msg.appendChild(approveWrapper);
    }
  }
}

window.addEventListener('DOMContentLoaded', () => {
  // Typewriter effect for initial message
  const prefs = getCubiePrefs();
  const initialMsg = prefs.name
    ? `Hi, I'm Cubie 👋 How can I help you?`
    : "Hi, I'm Cubie 👋 How can I help you?";
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
        <button class="suggestion-btn">📚 Application Help</button>
        <button class="suggestion-btn">📊 Analyze Data</button>
        <button class="suggestion-btn">📈 Visualize Data</button>
      `;
      msgDiv.after(suggestionBubbles);
      setTimeout(() => {
        suggestionBubbles.classList.add('visible');
      }, 50);
      // Suggestion bubble click handler
      suggestionBubbles.addEventListener('click', function(e) {
        if (e.target.classList.contains('suggestion-btn')) {
          const text = e.target.textContent.trim();
          // Mode switch buttons shouldn't hit backend immediately
          if (text.includes('Analyze Data')) {
            currentMode = 'analytics';
            addMessage("I'm ready to analyze your data! Ask me about shipments, disputes, invoices, or any specific metrics you want to explore.", 'bot', true);
            return;
          }
          if (text.includes('Application Help')) {
            currentMode = 'help';
            addMessage("Sure! I'm ready to answer any application questions. What would you like to know?", 'bot', true);
            userInput.value = '';
            return;
          }
          if (text.includes('Visualize Data')) {
            currentMode = 'analytics';
            addMessage("I can create charts and graphs for you! Tell me what data you want to visualize - shipments, disputes, invoices, or any specific metrics.", 'bot', true);
            return;
          }
          // For other suggestions, keep default behavior
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
  // --- Auto-detect analytics intent ------------------------------------
  if (currentMode === 'help') {
    const analyticsKeywords = [
      'shipment', 'dispute', 'invoice', 'chart', 'graph', 'plot',
      'average', 'sum', 'count', 'trend', 'kpi', 'heat map', 'heatmap',
      'bar chart', 'line chart', 'pie chart', 'stacked', 'percentage',
    ];
    const ql = question.toLowerCase();
    if (analyticsKeywords.some(k => ql.includes(k))) {
      currentMode = 'analytics';
    }
  }
  addMessage(question, 'user');
  userInput.value = '';
  typingIndicator.style.display = 'flex';
  try {
    // Build conversation history from current messages
    const messages = Array.from(document.querySelectorAll('.message'));
    const history = [];
    
    messages.forEach(msg => {
      if (msg.classList.contains('user')) {
        history.push({ role: 'user', content: msg.textContent.trim() });
      } else if (msg.classList.contains('bot')) {
        history.push({ role: 'assistant', content: msg.textContent.trim() });
      }
    });
    
    const response = await fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        question, 
        mode: currentMode, 
        prefs: cubiePrefs,
        history: history 
      }),
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
    micButton.style.background = 'transparent';
    micButton.style.color = '#666';
    isRecording = false;
    // Remove recording indicator
    const recordingMsg = document.getElementById('recording-message');
    if (recordingMsg) recordingMsg.remove();
  };

  recognition.onerror = (event) => {
    console.error('Speech recognition error:', event.error);
    micButton.style.background = 'transparent';
    micButton.style.color = '#666';
    isRecording = false;
    // Remove recording indicator
    const recordingMsg = document.getElementById('recording-message');
    if (recordingMsg) recordingMsg.remove();
  };

  recognition.onend = () => {
    micButton.style.background = 'transparent';
    micButton.style.color = '#666';
    isRecording = false;
    // Remove recording indicator
    const recordingMsg = document.getElementById('recording-message');
    if (recordingMsg) recordingMsg.remove();
  };

  micButton.addEventListener('click', () => {
    if (!isRecording) {
      recognition.start();
      micButton.style.background = '#004aad';
      micButton.style.color = '#fff';
      isRecording = true;
      
      // Add recording indicator message
      const recordingMsg = document.createElement('div');
      recordingMsg.id = 'recording-message';
      recordingMsg.className = 'message bot recording-indicator';
      recordingMsg.innerHTML = `
        <div class="message-content">
          🎤 <span class="recording-text">Listening... Speak now</span>
          <div class="recording-dots">
            <span></span><span></span><span></span>
          </div>
        </div>
      `;
      chatBox.appendChild(recordingMsg);
      scrollToBottom();
    } else {
      recognition.stop();
      micButton.style.background = 'transparent';
      micButton.style.color = '#666';
      isRecording = false;
      // Remove recording indicator
      const recordingMsg = document.getElementById('recording-message');
      if (recordingMsg) recordingMsg.remove();
    }
  });
} else {
  console.warn("Speech recognition not supported in this browser.");
  micButton.style.display = 'none';
}

// Add click handler for when microphone is blocked
micButton.addEventListener('click', () => {
  if (!('webkitSpeechRecognition' in window || 'SpeechRecognition' in window)) {
    alert('Voice input is not supported in this browser. Please use Chrome or Edge.');
    return;
  }
  
  if (!recognition) {
    alert('Microphone access is blocked. Please allow microphone access in your browser settings and refresh the page.');
    return;
  }
});

// === Notes System ===
function getSavedNotes() {
  try {
    return JSON.parse(localStorage.getItem('cubieNotes')) || [];
  } catch (e) {
    return [];
  }
}

function saveNotes(notes) {
  localStorage.setItem('cubieNotes', JSON.stringify(notes));
}

function addNote(content) {
  const notes = getSavedNotes();
  const newNote = {
    id: Date.now(),
    content: content,
    date: new Date().toLocaleString()
  };
  notes.unshift(newNote);
  saveNotes(notes);
  updateNotesDisplay();
}

function deleteNote(noteId) {
  const notes = getSavedNotes();
  const filteredNotes = notes.filter(note => note.id !== noteId);
  saveNotes(filteredNotes);
  updateNotesDisplay();
}

function updateNotesDisplay() {
  const notes = getSavedNotes();
  
  if (notes.length === 0) {
    notesList.style.display = 'none';
    notesEmpty.style.display = 'block';
    return;
  }
  
  notesList.style.display = 'block';
  notesEmpty.style.display = 'none';
  
  notesList.innerHTML = notes.map(note => `
    <div class="note-item">
      <div class="note-content">${note.content}</div>
      <div class="note-date">Saved: ${note.date}</div>
      <div class="note-actions">
        <button class="note-copy-btn" onclick="copyNoteToClipboard('${note.content.replace(/'/g, "\\'")}')">Copy</button>
        <button class="note-delete-btn" onclick="deleteNote(${note.id})">Delete</button>
      </div>
    </div>
  `).join('');
}

function copyNoteToClipboard(content) {
  navigator.clipboard.writeText(content).then(() => {
    // Show brief success feedback
    const btn = event.target;
    const originalText = btn.textContent;
    btn.textContent = 'Copied!';
    btn.style.background = '#28a745';
    setTimeout(() => {
      btn.textContent = originalText;
      btn.style.background = '#004aad';
    }, 1000);
  });
}

// Notes modal functionality
notesBtn.addEventListener('click', () => {
  updateNotesDisplay();
  notesModal.style.display = 'flex';
});

closeNotesBtn.addEventListener('click', () => {
  notesModal.style.display = 'none';
});


// Close modal when clicking outside
// Remove backdrop click functionality since there's no backdrop

// Interactive Data Analysis Interface
function showDataAnalysisInterface() {
  const analysisInterface = document.createElement('div');
  analysisInterface.className = 'analysis-interface';
  analysisInterface.innerHTML = `
    <div class="analysis-header">
      <h3>📊 Data Analysis</h3>
      <p>Choose a data category to explore:</p>
    </div>
    <div class="analysis-categories">
      <div class="category-card" data-category="shipments">
        <div class="category-icon">🚚</div>
        <h4>Shipments</h4>
        <p>Track delivery performance, routes, and carrier data</p>
        <div class="quick-queries">
          <button class="query-btn" data-query="shipment-performance">Performance Metrics</button>
          <button class="query-btn" data-query="carrier-analysis">Carrier Analysis</button>
          <button class="query-btn" data-query="route-optimization">Route Data</button>
        </div>
      </div>
      <div class="category-card" data-category="disputes">
        <div class="category-icon">⚖️</div>
        <h4>Disputes</h4>
        <p>Analyze dispute patterns, resolution times, and costs</p>
        <div class="quick-queries">
          <button class="query-btn" data-query="dispute-trends">Dispute Trends</button>
          <button class="query-btn" data-query="resolution-times">Resolution Times</button>
          <button class="query-btn" data-query="dispute-costs">Cost Analysis</button>
        </div>
      </div>
      <div class="category-card" data-category="invoices">
        <div class="category-icon">💰</div>
        <h4>Invoices</h4>
        <p>Review billing data, payment status, and financial metrics</p>
        <div class="quick-queries">
          <button class="query-btn" data-query="payment-status">Payment Status</button>
          <button class="query-btn" data-query="revenue-analysis">Revenue Analysis</button>
          <button class="query-btn" data-query="billing-trends">Billing Trends</button>
        </div>
      </div>
    </div>
    <div class="custom-query-section">
      <h4>Custom Query</h4>
      <textarea placeholder="Ask me anything about your data... (e.g., 'Show me average delivery times by carrier for the last 3 months')" class="custom-query-input"></textarea>
      <button class="analyze-btn">Analyze Data</button>
    </div>
  `;
  
  addMessage('', 'bot', false, analysisInterface);
  
  // Add event listeners for the interface
  analysisInterface.addEventListener('click', function(e) {
    if (e.target.classList.contains('query-btn')) {
      const query = e.target.dataset.query;
      const category = e.target.closest('.category-card').dataset.category;
      executeQuickQuery(query, category);
    }
  });
  
  const analyzeBtn = analysisInterface.querySelector('.analyze-btn');
  const customInput = analysisInterface.querySelector('.custom-query-input');
  
  analyzeBtn.addEventListener('click', function() {
    const customQuery = customInput.value.trim();
    if (customQuery) {
      userInput.value = customQuery;
      form.dispatchEvent(new Event('submit'));
    }
  });
}

// Interactive Data Visualization Interface
function showDataVisualizationInterface() {
  const visualizationInterface = document.createElement('div');
  visualizationInterface.className = 'visualization-interface';
  visualizationInterface.innerHTML = `
    <div class="viz-header">
      <h3>📈 Data Visualization</h3>
      <p>Create custom charts and graphs from your data:</p>
    </div>
    <div class="chart-builder">
      <div class="chart-type-selector">
        <h4>Chart Type</h4>
        <div class="chart-types">
          <button class="chart-type-btn active" data-type="line">📈 Line Chart</button>
          <button class="chart-type-btn" data-type="bar">📊 Bar Chart</button>
          <button class="chart-type-btn" data-type="stacked">📊 Stacked Bar</button>
          <button class="chart-type-btn" data-type="heatmap">🔥 Heatmap</button>
        </div>
      </div>
      <div class="data-source-selector">
        <h4>Data Source</h4>
        <select class="data-source-select">
          <option value="shipments">Shipments</option>
          <option value="disputes">Disputes</option>
          <option value="invoices">Invoices</option>
        </select>
      </div>
      <div class="quick-visualizations">
        <h4>Quick Visualizations</h4>
        <div class="quick-viz-buttons">
          <button class="quick-viz-btn" data-viz="delivery-trends">Delivery Performance Trends</button>
          <button class="quick-viz-btn" data-viz="carrier-comparison">Carrier Comparison</button>
          <button class="quick-viz-btn" data-viz="dispute-heatmap">Dispute Patterns</button>
          <button class="quick-viz-btn" data-viz="revenue-chart">Revenue Analysis</button>
        </div>
      </div>
      <div class="custom-viz-section">
        <h4>Custom Visualization</h4>
        <textarea placeholder="Describe what you want to visualize... (e.g., 'Show me a line chart of monthly shipment volumes by carrier')" class="custom-viz-input"></textarea>
        <button class="visualize-btn">Create Chart</button>
      </div>
    </div>
  `;
  
  addMessage('', 'bot', false, visualizationInterface);
  
  // Add event listeners for the interface
  visualizationInterface.addEventListener('click', function(e) {
    if (e.target.classList.contains('chart-type-btn')) {
      // Remove active class from all buttons
      visualizationInterface.querySelectorAll('.chart-type-btn').forEach(btn => btn.classList.remove('active'));
      // Add active class to clicked button
      e.target.classList.add('active');
    }
    
    if (e.target.classList.contains('quick-viz-btn')) {
      const vizType = e.target.dataset.viz;
      executeQuickVisualization(vizType);
    }
  });
  
  const visualizeBtn = visualizationInterface.querySelector('.visualize-btn');
  const customVizInput = visualizationInterface.querySelector('.custom-viz-input');
  const chartTypeSelect = visualizationInterface.querySelector('.chart-type-btn.active');
  const dataSourceSelect = visualizationInterface.querySelector('.data-source-select');
  
  visualizeBtn.addEventListener('click', function() {
    const customViz = customVizInput.value.trim();
    const chartType = chartTypeSelect.dataset.type;
    const dataSource = dataSourceSelect.value;
    
    if (customViz) {
      const fullQuery = `Create a ${chartType} chart showing: ${customViz}`;
      userInput.value = fullQuery;
      form.dispatchEvent(new Event('submit'));
    }
  });
}

// Execute quick queries
function executeQuickQuery(queryType, category) {
  const queries = {
    'shipment-performance': 'Show me shipment performance metrics including on-time delivery rates, average transit times, and delivery success rates',
    'carrier-analysis': 'Analyze carrier performance including cost per shipment, delivery times, and reliability metrics',
    'route-optimization': 'Show me route data and optimization opportunities including distance analysis and delivery patterns',
    'dispute-trends': 'Show me dispute trends over time including dispute types, frequency, and resolution patterns',
    'resolution-times': 'Analyze dispute resolution times by category and identify bottlenecks in the resolution process',
    'dispute-costs': 'Show me dispute cost analysis including average dispute amounts and financial impact',
    'payment-status': 'Show me invoice payment status analysis including overdue payments and payment trends',
    'revenue-analysis': 'Analyze revenue data including monthly trends, customer revenue, and revenue by service type',
    'billing-trends': 'Show me billing trends and patterns including invoice volumes and billing cycle analysis'
  };
  
  const query = queries[queryType];
  if (query) {
    userInput.value = query;
    form.dispatchEvent(new Event('submit'));
  }
}

// Execute quick visualizations
function executeQuickVisualization(vizType) {
  const visualizations = {
    'delivery-trends': 'Create a line chart showing delivery performance trends over the last 6 months',
    'carrier-comparison': 'Create a bar chart comparing carrier performance metrics',
    'dispute-heatmap': 'Create a heatmap showing dispute patterns by region and time',
    'revenue-chart': 'Create a stacked bar chart showing monthly revenue breakdown by service type'
  };
  
  const vizQuery = visualizations[vizType];
  if (vizQuery) {
    userInput.value = vizQuery;
    form.dispatchEvent(new Event('submit'));
  }
}
