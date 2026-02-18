// ===============================
// Le Magicien IA - app.js (complet, corrigé)
// Cohérent avec app.py (question.total_questions, tiebreaker, feedback)
// ===============================

// Variables globales
let currentQuestion = null;
let currentQuestionNumber = 1;

// Ces constantes ne doivent PAS piloter l’UI si app.py renvoie total_questions.
// On les garde seulement comme fallback.
const FALLBACK_TOTAL_QUESTIONS = 7;
const FALLBACK_MAX_WITH_TIEBREAKER = 8;

// Total courant côté UI (piloté par le backend)
let currentTotalQuestions = FALLBACK_TOTAL_QUESTIONS;

// Stocke la prédiction courante (pour le feedback)
window.currentPrediction = "";

// -----------------------------
// Utils DOM
// -----------------------------
function $(id) {
  return document.getElementById(id);
}

// Afficher un écran spécifique
function showScreen(screenId) {
  const screens = document.querySelectorAll(".screen");
  screens.forEach((screen) => screen.classList.remove("active"));

  const targetScreen = document.getElementById(screenId);
  if (targetScreen) targetScreen.classList.add("active");
}

// Helpers UI
function setButtonsDisabled(disabled) {
  const buttons = document.querySelectorAll(".answer-button");
  buttons.forEach((btn) => (btn.disabled = disabled));
}

function hideActualWordBlock() {
  const block = $("actual-word-block");
  const input = $("actual-word-input");
  if (block) block.style.display = "none";
  if (input) input.value = "";
}

function showActualWordBlock() {
  const block = $("actual-word-block");
  const input = $("actual-word-input");
  if (block) block.style.display = "block";
  if (input) {
    input.value = "";
    input.focus();
  }
}

// Met à jour la barre de progression + texte "Question X sur Y"
function updateProgressUI(qNum, total) {
  const questionNumberEl = $("question-number");
  const questionTotalEl = $("question-total");
  const progressFill = $("progress-fill");

  const safeTotal = Number.isFinite(total) && total > 0 ? total : currentTotalQuestions;

  if (questionNumberEl) questionNumberEl.textContent = String(qNum);
  if (questionTotalEl) questionTotalEl.textContent = String(safeTotal);

  const progress = Math.min(100, (qNum / safeTotal) * 100);
  if (progressFill) progressFill.style.width = progress + "%";
}

// Applique les infos d’une question backend (numéro + total)
function syncQuestionMeta(question) {
  // question_number
  const qNum = question?.question_number;
  if (Number.isFinite(qNum) && qNum > 0) currentQuestionNumber = qNum;

  // total_questions
  const total = question?.total_questions;
  if (Number.isFinite(total) && total > 0) currentTotalQuestions = total;
}

// -----------------------------
// API helpers
// -----------------------------
async function postJSON(url, payload) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload ?? {}),
  });

  let data = null;
  try {
    data = await res.json();
  } catch (_) {
    // pas de json
  }

  if (!res.ok) {
    const msg =
      (data && (data.error || data.message)) ||
      `HTTP ${res.status} sur ${url}`;
    throw new Error(msg);
  }

  return data;
}

// -----------------------------
// Démarrer le jeu
// -----------------------------
async function startGame() {
  try {
    hideActualWordBlock();
    setButtonsDisabled(true);

    // reset état
    currentQuestion = null;
    currentQuestionNumber = 1;
    currentTotalQuestions = FALLBACK_TOTAL_QUESTIONS;
    window.currentPrediction = "";

    const data = await postJSON("/start", {});

    if (!data || !data.success || !data.question) {
      console.error("Réponse /start invalide:", data);
      alert(data?.error || "Réponse /start invalide. Réessaie.");
      return;
    }

    // ✅ source de vérité = data.question
    currentQuestion = data.question;

    // ✅ sync meta depuis l'objet question (question_number / total_questions)
    syncQuestionMeta(currentQuestion);

    showScreen("question-screen");

    // ✅ displayQuestion doit lire currentQuestion.question_number etc.
    displayQuestion(currentQuestion);
  } catch (error) {
    console.error("Erreur lors du démarrage:", error);
    alert("Une erreur est survenue au démarrage. Veuillez réessayer.");
  } finally {
    // ✅ toujours réactiver, même si erreur
    setButtonsDisabled(false);
  }
}


// -----------------------------
// Afficher une question
// -----------------------------
function displayQuestion(question) {
  const questionText = $("question-text");

  // synchro meta (num + total)
  syncQuestionMeta(question);

  const qNum = currentQuestionNumber || 1;
  const total = currentTotalQuestions || FALLBACK_TOTAL_QUESTIONS;

  updateProgressUI(qNum, total);

  // Texte de question (petite animation)
  if (questionText) {
    questionText.style.opacity = "0";
    setTimeout(() => {
      questionText.textContent = question?.text || "";
      questionText.style.opacity = "1";
    }, 150);
  }
}

// -----------------------------
// Répondre à une question
// -----------------------------
async function answerQuestion(answer) {
  if (!currentQuestion) return;

  const buttons = document.querySelectorAll('.answer-button');
  buttons.forEach(btn => (btn.disabled = true));

  try {
    const response = await fetch('/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question_id: currentQuestion.id,
        // IMPORTANT: null doit rester null pour "je ne sais pas"
        answer: answer === undefined ? null : answer
      })
    });

    const data = await response.json();

    // ✅ si le backend dit "success:false", on ne freeze pas
    if (!data.success) {
      console.error('Backend error:', data);
      alert(data.error || "Une erreur est survenue côté serveur.");
      return;
    }

    if (data.done) {
      displayPrediction(data.prediction, data.candidates);
      return;
    }

    // ✅ le numéro est dans data.question.question_number
    currentQuestion = data.question;

    setTimeout(() => {
      displayQuestion(data.question, data.question.question_number);
    }, 250);

  } catch (error) {
    console.error('Erreur lors de la réponse:', error);
    alert('Une erreur est survenue. Veuillez réessayer.');
  } finally {
    // ✅ toujours réactiver si on n'est pas sur l'écran final
    // (si displayPrediction change d’écran, ces boutons ne servent plus)
    buttons.forEach(btn => (btn.disabled = false));
  }
}



// -----------------------------
// Afficher la prédiction
// -----------------------------
function displayPrediction(prediction, candidates) {
  showScreen("prediction-screen");

  const predictedWordEl = $("predicted-word");
  const alternativesContainer = $("alternatives-container");
  const alternativesList = $("alternatives-list");

  // prédiction “courante” (celle qui sera envoyée dans /feedback)
  window.currentPrediction = prediction || "";

  // Affiche le mot principal
  if (predictedWordEl) {
    predictedWordEl.style.opacity = "0";
    setTimeout(() => {
      predictedWordEl.textContent = (window.currentPrediction || "").toUpperCase();
      predictedWordEl.style.opacity = "1";
    }, 250);
  }

  // ---- Alternatives cliquables ----
  if (alternativesContainer && alternativesList) {
    const list = Array.isArray(candidates) ? candidates : [];
    const filtered = list
      .filter((w) => w && w !== prediction)
      .slice(0, 3);

    if (filtered.length > 0) {
      alternativesContainer.style.display = "block";
      alternativesList.innerHTML = "";

      filtered.forEach((w) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "alternative-button";
        btn.textContent = w;

        btn.addEventListener("click", () => {
          // remplace la prédiction par l'alternative choisie
          window.currentPrediction = w;

          if (predictedWordEl) {
            predictedWordEl.style.opacity = "0";
            setTimeout(() => {
              predictedWordEl.textContent = w.toUpperCase();
              predictedWordEl.style.opacity = "1";
            }, 120);
          }
        });

        alternativesList.appendChild(btn);
      });
    } else {
      alternativesContainer.style.display = "none";
      alternativesList.innerHTML = "";
    }
  }
}


// -----------------------------
// Feedback
// -----------------------------
async function giveFeedback(correct) {
  const feedbackTitle = $("feedback-title");
  const feedbackMessage = $("feedback-message");

  hideActualWordBlock();

  if (correct) {
    if (feedbackTitle) {
      feedbackTitle.textContent = "✨ Extraordinaire ! ✨";
      feedbackTitle.className = "feedback-title glow";
    }
    if (feedbackMessage) {
      feedbackMessage.textContent =
        "J'ai réussi à lire dans vos pensées ! Voulez-vous essayer à nouveau avec un autre mot ?";
    }

    // Envoi feedback positif
    try {
      await postJSON("/feedback", {
        correct: true,
        predicted: window.currentPrediction,
        actual_word: window.currentPrediction,
      });
    } catch (error) {
      console.error("Erreur lors de l'envoi du feedback:", error);
    }

    showScreen("feedback-screen");
    return;
  }

  // incorrect
  if (feedbackTitle) {
    feedbackTitle.textContent = "Presque ! 🔮";
    feedbackTitle.className = "feedback-title";
  }
  if (feedbackMessage) {
    feedbackMessage.textContent =
      "Même les plus grands magiciens peuvent se tromper… Dis-moi le mot auquel tu pensais pour que je m'améliore !";
  }

  showActualWordBlock();
  showScreen("feedback-screen");
}

// Envoyer le vrai mot quand c’est faux
async function submitActualWord() {
  const input = $("actual-word-input");
  const actual = (input ? input.value : "").trim();

  if (!actual) {
    alert("Écris d'abord le mot auquel tu pensais 🙂");
    return;
  }

  try {
    const data = await postJSON("/feedback", {
      correct: false,
      predicted: window.currentPrediction || "",
      actual_word: actual,
    });

    // confirmation visuelle
    const feedbackMessage = $("feedback-message");
    if (data && data.message && feedbackMessage) {
      feedbackMessage.textContent = data.message;
    }

    hideActualWordBlock();
  } catch (e) {
    console.error("Erreur submitActualWord:", e);
    alert("Impossible d'envoyer le mot. Réessaie.");
  }
}

// -----------------------------
// Recommencer le jeu
// -----------------------------
function restartGame() {
  currentQuestion = null;
  currentQuestionNumber = 1;
  currentTotalQuestions = FALLBACK_TOTAL_QUESTIONS;
  window.currentPrediction = "";
  hideActualWordBlock();

  // reset progress
  const progressFill = $("progress-fill");
  if (progressFill) progressFill.style.width = "0%";

  // reset texte compteur
  const questionNumberEl = $("question-number");
  const questionTotalEl = $("question-total");
  if (questionNumberEl) questionNumberEl.textContent = "1";
  if (questionTotalEl) questionTotalEl.textContent = String(FALLBACK_TOTAL_QUESTIONS);

  showScreen("welcome-screen");
}

// -----------------------------
// Gestion clavier
// -----------------------------
document.addEventListener("keydown", (event) => {
  const activeScreen = document.querySelector(".screen.active");
  if (!activeScreen) return;

  if (activeScreen.id === "question-screen") {
    // évite de spammer quand les boutons sont désactivés
    const anyDisabled = Array.from(document.querySelectorAll(".answer-button")).some(
      (b) => b.disabled
    );
    if (anyDisabled) return;

    if (event.key === "ArrowLeft" || event.key === "n" || event.key === "N") {
      answerQuestion(false);
    } else if (
      event.key === "ArrowRight" ||
      event.key === "o" ||
      event.key === "O" ||
      event.key === "y" ||
      event.key === "Y"
    ) {
      answerQuestion(true);
    } else if (event.key === "Enter") {
      answerQuestion(null);
    }
  } else if (activeScreen.id === "welcome-screen") {
    if (event.key === "Enter" || event.key === " ") startGame();
  } else if (activeScreen.id === "feedback-screen") {
    const block = $("actual-word-block");
    const visible = block && block.style.display !== "none";
    if (event.key === "Enter" && visible) {
      submitActualWord();
    } else if (event.key === "Enter" || event.key === " ") {
      restartGame();
    }
  }
});

// -----------------------------
// Animation crystal hover (si CSS animation existe)
// -----------------------------
document.addEventListener("DOMContentLoaded", () => {
  const crystals = document.querySelectorAll(".crystal");
  crystals.forEach((crystal) => {
    crystal.addEventListener("mouseenter", () => {
      crystal.style.animation = "crystal-pulse 0.5s ease-in-out";
    });
    crystal.addEventListener("mouseleave", () => {
      crystal.style.animation = "crystal-pulse 2s ease-in-out infinite";
    });
  });

  // reset UI compteur au chargement
  const questionTotalEl = $("question-total");
  if (questionTotalEl) questionTotalEl.textContent = String(FALLBACK_TOTAL_QUESTIONS);
});

// Expose au global (car index.html appelle startGame(), answerQuestion(), etc.)
window.startGame = startGame;
window.answerQuestion = answerQuestion;
window.giveFeedback = giveFeedback;
window.submitActualWord = submitActualWord;
window.restartGame = restartGame;
