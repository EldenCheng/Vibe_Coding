export class Timer {
  #element;
  #duration;
  #remaining;
  #intervalId = null;
  #onTimeout;

  constructor(element, onTimeout) {
    this.#element = element;
    this.#onTimeout = onTimeout;
  }

  start(duration) {
    this.#duration = duration;
    this.#remaining = duration;
    this.#element.textContent = `⏱ ${this.#remaining}`;
    this.#element.classList.remove('hidden', 'urgent');
    this.#element.classList.add('active');

    this.#intervalId = setInterval(() => {
      this.#tick();
    }, 1000);
  }

  stop() {
    if (this.#intervalId) {
      clearInterval(this.#intervalId);
      this.#intervalId = null;
    }
    this.#element.classList.remove('active');
  }

  #tick() {
    this.#remaining--;
    this.#element.textContent = `⏱ ${this.#remaining}`;

    if (this.#remaining <= 15) {
      this.#element.classList.add('urgent');
    }

    if (this.#remaining <= 0) {
      this.stop();
      if (this.#onTimeout) this.#onTimeout();
    }
  }

  reset() {
    this.stop();
    this.#element.classList.remove('urgent');
  }
}
