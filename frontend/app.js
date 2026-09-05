const messagesEl = document.getElementById("messages");
const formEl = document.getElementById("chat-form");
const inputEl = document.getElementById("chat-input");
const playerHintEl = document.getElementById("player-hint");

const history = [];
let player = null;
let currentVideoId = null;

// Called by the YouTube IFrame API script once it has loaded.
window.onYouTubeIframeAPIReady = function () {
  player = new YT.Player("player", {
    height: "100%",
    width: "100%",
    playerVars: { rel: 0 },
  });
};

function seekTo(videoId, startSeconds) {
  if (!player) return;
  if (currentVideoId !== videoId) {
    currentVideoId = videoId;
    player.loadVideoById({ videoId, startSeconds });
  } else {
    player.seekTo(startSeconds, true);
    player.playVideo();
  }
  playerHintEl.textContent = "Playing from the cited moment.";
}

function addBubble(role, text) {
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}`;
  bubble.textContent = text;
  messagesEl.appendChild(bubble);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return bubble;
}

function renderCitations(container, citations) {
  if (!citations.length) return;
  const wrap = document.createElement("div");
  wrap.className = "citations";
  for (const c of citations) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "citation-chip";
    chip.textContent = `Source ${c.index} — ${c.title} @ ${c.timestamp}`;
    chip.addEventListener("click", () => seekTo(c.video_id, c.start_seconds));
    wrap.appendChild(chip);
  }
  container.appendChild(wrap);
}

// Parses "event: X\ndata: Y\n\n" frames off an SSE stream sent via fetch (not EventSource,
// since EventSource can't send a POST body — we need one to pass question + history).
async function streamChat(question, onCitations, onToken) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, history }),
  });

  if (!response.ok || !response.body) {
    throw new Error(`Request failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);

      const eventLine = frame.split("\n").find((l) => l.startsWith("event: "));
      const dataLine = frame.split("\n").find((l) => l.startsWith("data: "));
      if (!eventLine || !dataLine) continue;

      const event = eventLine.slice("event: ".length);
      const data = JSON.parse(dataLine.slice("data: ".length));

      if (event === "citations") onCitations(data.citations);
      else if (event === "token") onToken(data.text);
    }
  }
}

formEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = inputEl.value.trim();
  if (!question) return;

  inputEl.value = "";
  inputEl.disabled = true;

  addBubble("user", question);
  const assistantBubble = addBubble("assistant", "");
  let answerText = "";
  let citationsContainer = null;

  try {
    await streamChat(
      question,
      (citations) => {
        citationsContainer = document.createElement("div");
        assistantBubble.after(citationsContainer);
        renderCitations(citationsContainer, citations);
      },
      (token) => {
        answerText += token;
        assistantBubble.textContent = answerText;
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }
    );
    history.push({ role: "user", content: question });
    history.push({ role: "assistant", content: answerText });
  } catch (err) {
    assistantBubble.classList.add("error");
    assistantBubble.textContent = `Something went wrong: ${err.message}`;
  } finally {
    inputEl.disabled = false;
    inputEl.focus();
  }
});
