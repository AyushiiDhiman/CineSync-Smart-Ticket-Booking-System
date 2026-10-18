const API_BASE = "http://localhost:5000";
const POSTER_EMOJIS = ["🎬", "🔥", "⚡", "🦁", "👻"]; // just visual variety per movie card

// screens
const nameScreenEl = document.getElementById("nameScreen");
const moviesScreenEl = document.getElementById("moviesScreen");
const bookingScreenEl = document.getElementById("bookingScreen");
const paymentScreenEl = document.getElementById("paymentScreen");
const receiptScreenEl = document.getElementById("receiptScreen");
const bookingsScreenEl = document.getElementById("bookingsScreen");
const reviewsScreenEl = document.getElementById("reviewsScreen");
const allScreens = [moviesScreenEl, bookingScreenEl, paymentScreenEl, receiptScreenEl, bookingsScreenEl, reviewsScreenEl];

// name entry
const nameInputEl = document.getElementById("nameInput");
const nameSubmitEl = document.getElementById("nameSubmit");
const nameErrorEl = document.getElementById("nameError");
const userNameDisplayEl = document.getElementById("userNameDisplay");

// movies
const movieGridEl = document.getElementById("movieGrid");

// booking
const bookingMovieTitleEl = document.getElementById("bookingMovieTitle");
const bookingMovieMetaEl = document.getElementById("bookingMovieMeta");
const seatMapEl = document.getElementById("seatMap");
const statusMsgEl = document.getElementById("statusMsg");
const activityLogEl = document.getElementById("activityLog");
const activityToggleEl = document.getElementById("activityToggle");
const activityArrowEl = document.getElementById("activityArrow");

// payment
const payMovieTitleEl = document.getElementById("payMovieTitle");
const paySeatNoEl = document.getElementById("paySeatNo");
const payNowBtn = document.getElementById("payNowBtn");
const payCancelBtn = document.getElementById("payCancelBtn");
const paymentStatusEl = document.getElementById("paymentStatus");

// receipt / food
const receiptBookingIdEl = document.getElementById("receiptBookingId");
const receiptSeatNoEl = document.getElementById("receiptSeatNo");
const foodListEl = document.getElementById("foodList");
const addFoodBtn = document.getElementById("addFoodBtn");
const skipFoodBtn = document.getElementById("skipFoodBtn");
const foodStatusEl = document.getElementById("foodStatus");

// nav + bookings + reviews
const navLinks = document.querySelectorAll(".nav-links li[data-nav]");
const bookingsListEl = document.getElementById("bookingsList");
const reviewMovieSelectEl = document.getElementById("reviewMovieSelect");
const reviewFeedEl = document.getElementById("reviewFeed");
const reviewInputEl = document.getElementById("reviewInput");
const ratingSelectEl = document.getElementById("ratingSelect");
const reviewSendBtn = document.getElementById("reviewSendBtn");

let currentUser = null;
let allMovies = [];
let selectedMovie = null;    // { movie_id, title, show_id, ... }
let pendingSeat = null;      // { id, seatNo }
let lastBookingId = null;

let seatPollTimer = null;
let activityPollTimer = null;
let reviewPollTimer = null;

function showScreen(screenEl) {
  allScreens.forEach(s => s.classList.add("hidden"));
  screenEl.classList.remove("hidden");
}

function stopAllPolling() {
  clearInterval(seatPollTimer);
  clearInterval(activityPollTimer);
  clearInterval(reviewPollTimer);
}

// --- name entry ---

nameSubmitEl.addEventListener("click", submitName);
nameInputEl.addEventListener("keydown", e => { if (e.key === "Enter") submitName(); });

async function submitName() {
  const name = nameInputEl.value.trim();
  if (!name) { nameErrorEl.textContent = "Please enter your name"; return; }

  nameErrorEl.textContent = "";
  nameSubmitEl.textContent = "Loading...";

  try {
    const res = await fetch(`${API_BASE}/api/users/lookup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name })
    });
    if (!res.ok) throw new Error("backend error");

    currentUser = await res.json();
    userNameDisplayEl.textContent = currentUser.name;

    nameScreenEl.classList.add("hidden");
    showScreen(moviesScreenEl);
    loadMovies();

  } catch (err) {
    nameErrorEl.textContent = "Couldn't reach the backend - is app.py running?";
    nameSubmitEl.textContent = "Continue";
  }
}

// --- nav ---

navLinks.forEach(link => {
  link.addEventListener("click", () => {
    navLinks.forEach(l => l.classList.remove("active"));
    link.classList.add("active");
    stopAllPolling();

    if (link.dataset.nav === "movies") {
      showScreen(moviesScreenEl);
      loadMovies();
    } else if (link.dataset.nav === "bookings") {
      showScreen(bookingsScreenEl);
      loadMyBookings();
    } else if (link.dataset.nav === "reviews") {
      showScreen(reviewsScreenEl);
      openReviews();
    }
  });
});

// --- movie selection ---

async function loadMovies() {
  movieGridEl.innerHTML = "Loading movies...";
  try {
    const res = await fetch(`${API_BASE}/api/movies`);
    allMovies = await res.json();

    movieGridEl.innerHTML = "";
    allMovies.forEach((m, i) => {
      const card = document.createElement("div");
      card.className = "movie-card";
      const time = new Date(m.show_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      card.innerHTML = `
        <div class="movie-poster poster-${i % 5}">${POSTER_EMOJIS[i % 5]}</div>
        <div class="movie-body">
          <h3>${m.title}</h3>
          <p>${m.theatre_name} &middot; ${time} &middot; ${m.duration_min} min</p>
        </div>
      `;
      card.addEventListener("click", () => openBooking(m));
      movieGridEl.appendChild(card);
    });
  } catch (err) {
    movieGridEl.innerHTML = "Couldn't load movies.";
  }
}

function openBooking(movie) {
  selectedMovie = movie;
  bookingMovieTitleEl.textContent = movie.title;
  bookingMovieMetaEl.textContent =
    `${movie.theatre_name} \u00b7 ${new Date(movie.show_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} \u00b7 ${movie.duration_min} min`;

  showScreen(bookingScreenEl);
  loadSeats();
  loadActivityLog();
  seatPollTimer = setInterval(loadSeats, 3000);
  activityPollTimer = setInterval(loadActivityLog, 2000);
}

// --- activity log (makes locking/scheduler visible) ---

activityToggleEl.addEventListener("click", () => {
  activityLogEl.classList.toggle("collapsed");
  activityArrowEl.textContent = activityLogEl.classList.contains("collapsed") ? "▸" : "▾";
});

async function loadActivityLog() {
  try {
    const res = await fetch(`${API_BASE}/api/activity-log`);
    const entries = await res.json();

    activityLogEl.innerHTML = entries.length
      ? entries.map(e => `<div class="log-line"><span class="log-time">[${e.time}]</span>${e.message}</div>`).join("")
      : "<div class='log-line'>No activity yet - select a seat to see locking in action.</div>";
  } catch (err) {
    // quietly ignore - this panel isn't critical to the main flow
  }
}

// --- seat map ---

async function loadSeats() {
  if (!selectedMovie) return;
  try {
    const res = await fetch(`${API_BASE}/api/shows/${selectedMovie.show_id}/seats`);
    const seats = await res.json();
    renderSeats(seats);
  } catch (err) {
    seatMapEl.innerHTML = "Couldn't reach the backend.";
  }
}

function renderSeats(seats) {
  seatMapEl.innerHTML = "";
  seats.forEach(seat => {
    const seatDiv = document.createElement("div");
    seatDiv.className = `seat ${seat.status}`;
    seatDiv.textContent = seat.seat_no;
    if (seat.status === "available") {
      seatDiv.addEventListener("click", () => openPaymentScreen(seat.id, seat.seat_no));
    }
    seatMapEl.appendChild(seatDiv);
  });
}

// --- hold + payment ---

async function openPaymentScreen(seatId, seatNo) {
  statusMsgEl.textContent = `Holding seat ${seatNo}...`;

  const holdRes = await fetch(`${API_BASE}/api/seats/${seatId}/hold`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: currentUser.id })
  });

  if (!holdRes.ok) {
    const err = await holdRes.json();
    statusMsgEl.textContent = `Couldn't hold seat ${seatNo}: ${err.error}`;
    loadSeats();
    return;
  }

  pendingSeat = { id: seatId, seatNo };
  payMovieTitleEl.textContent = selectedMovie.title;
  paySeatNoEl.textContent = seatNo;
  paymentStatusEl.textContent = "";
  payNowBtn.disabled = false;
  payNowBtn.textContent = "Pay Now";

  clearInterval(seatPollTimer);
  clearInterval(activityPollTimer);
  showScreen(paymentScreenEl);
}

payCancelBtn.addEventListener("click", () => {
  pendingSeat = null;
  showScreen(bookingScreenEl);
  loadSeats();
  loadActivityLog();
  seatPollTimer = setInterval(loadSeats, 3000);
  activityPollTimer = setInterval(loadActivityLog, 2000);
});

payNowBtn.addEventListener("click", async () => {
  if (!pendingSeat) return;

  payNowBtn.disabled = true;
  payNowBtn.textContent = "Processing...";
  paymentStatusEl.textContent = "";

  const bookRes = await fetch(`${API_BASE}/api/seats/${pendingSeat.id}/book`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: currentUser.id, amount: 250.0 })
  });

  const bookData = await bookRes.json();

  if (bookRes.ok) {
    lastBookingId = bookData.booking_id;
    receiptBookingIdEl.textContent = bookData.booking_id;
    receiptSeatNoEl.textContent = pendingSeat.seatNo;
    loadFoodItems();
    showScreen(receiptScreenEl);
  } else {
    paymentStatusEl.textContent = `Payment failed: ${bookData.error}. Seat released, try again.`;
    payNowBtn.disabled = false;
    payNowBtn.textContent = "Pay Now";
  }
});

// --- food ordering ---

async function loadFoodItems() {
  foodListEl.innerHTML = "Loading menu...";
  try {
    const res = await fetch(`${API_BASE}/api/food-items`);
    const items = await res.json();

    foodListEl.innerHTML = "";
    items.forEach(item => {
      const row = document.createElement("div");
      row.className = "food-item-row";
      row.innerHTML = `
        <label>
          <input type="checkbox" value="${item.id}" class="food-checkbox">
          ${item.name}
        </label>
        <span>₹${item.price}</span>
      `;
      foodListEl.appendChild(row);
    });
  } catch (err) {
    foodListEl.innerHTML = "Couldn't load menu.";
  }
}

addFoodBtn.addEventListener("click", async () => {
  const checked = document.querySelectorAll(".food-checkbox:checked");
  const items = Array.from(checked).map(cb => ({ food_item_id: parseInt(cb.value), quantity: 1 }));

  if (items.length === 0) {
    foodStatusEl.textContent = "Select at least one item, or tap Skip.";
    return;
  }

  const res = await fetch(`${API_BASE}/api/bookings/${lastBookingId}/food-order`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items })
  });

  if (res.ok) {
    foodStatusEl.style.color = "#4fd394";
    foodStatusEl.textContent = "Food order added! Enjoy the movie.";
    addFoodBtn.disabled = true;
  } else {
    foodStatusEl.textContent = "Couldn't add food order, try again.";
  }
});

skipFoodBtn.addEventListener("click", () => {
  pendingSeat = null;
  addFoodBtn.disabled = false;
  showScreen(moviesScreenEl);
  loadMovies();
});

// --- my bookings ---

async function loadMyBookings() {
  bookingsListEl.innerHTML = "Loading...";

  try {
    const res = await fetch(`${API_BASE}/api/users/${currentUser.id}/bookings`);
    const bookings = await res.json();

    if (bookings.length === 0) {
      bookingsListEl.innerHTML = "<p>No bookings yet.</p>";
      return;
    }

    bookingsListEl.innerHTML = "";
    bookings.forEach(b => {
      const card = document.createElement("div");
      card.className = "booking-card";
      card.innerHTML = `
        <div class="title-row">
          <span>${b.movie_title}</span>
          <span class="status-${b.state}">${b.state}</span>
        </div>
        <div>Seat: ${b.seat_no} &middot; Booking #${b.booking_id}</div>
        <div>Amount: ₹${b.amount ?? "-"} (${b.payment_status ?? "n/a"})</div>
      `;
      bookingsListEl.appendChild(card);
    });
  } catch (err) {
    bookingsListEl.innerHTML = "Couldn't load bookings.";
  }
}

// --- reviews / live chat ---

async function openReviews() {
  if (allMovies.length === 0) {
    try {
      const res = await fetch(`${API_BASE}/api/movies`);
      allMovies = await res.json();
    } catch (err) {
      reviewFeedEl.innerHTML = "Couldn't load movies.";
      return;
    }
  }

  reviewMovieSelectEl.innerHTML = allMovies
    .map(m => `<option value="${m.movie_id}">${m.title}</option>`)
    .join("");

  loadReviews();
  reviewPollTimer = setInterval(loadReviews, 3000); // this polling is what makes it feel "live"
}

reviewMovieSelectEl.addEventListener("change", loadReviews);

async function loadReviews() {
  const movieId = reviewMovieSelectEl.value;
  if (!movieId) return;

  try {
    const res = await fetch(`${API_BASE}/api/movies/${movieId}/reviews`);
    const reviews = await res.json();

    reviewFeedEl.innerHTML = reviews.length
      ? reviews.map(r => `
          <div class="review-bubble">
            <div class="review-head">
              <span>${r.user_name}</span>
              <span class="review-stars">${"★".repeat(r.rating)}${"☆".repeat(5 - r.rating)}</span>
            </div>
            <div>${r.comment}</div>
          </div>
        `).join("")
      : "<p>No reviews yet - be the first to say something!</p>";

    reviewFeedEl.scrollTop = reviewFeedEl.scrollHeight;
  } catch (err) {
    reviewFeedEl.innerHTML = "Couldn't load reviews.";
  }
}

reviewSendBtn.addEventListener("click", sendReview);
reviewInputEl.addEventListener("keydown", e => { if (e.key === "Enter") sendReview(); });

async function sendReview() {
  const comment = reviewInputEl.value.trim();
  const movieId = reviewMovieSelectEl.value;
  if (!comment || !movieId) return;

  await fetch(`${API_BASE}/api/movies/${movieId}/reviews`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: currentUser.id,
      rating: parseInt(ratingSelectEl.value),
      comment
    })
  });

  reviewInputEl.value = "";
  loadReviews();
}
