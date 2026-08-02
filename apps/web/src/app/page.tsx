const domains = [
  ["Нормативи", "Статути, накази, доктрини"],
  ["Навчання", "Маршрути, заняття, перевірка знань"],
  ["Діловодство", "Чернетки за перевіреними шаблонами"],
  ["Довідник", "Пошук з точними цитатами"],
] as const;

export default function Home() {
  return (
    <main>
      <header>
        <div><strong>КОРПУС</strong><span> · доказова система</span></div>
        <div className="status">● Локальний режим</div>
      </header>
      <section className="hero">
        <p className="eyebrow">ВІДПОВІДІ, ЯКІ МОЖНА ПЕРЕВІРИТИ</p>
        <h1>Знайти джерело.<br />Зрозуміти відповідь.</h1>
        <p>Система показує документ, редакцію, пункт і сторінку. Якщо доказів недостатньо — прямо про це повідомляє.</p>
        <form>
          <label htmlFor="query">Запит до перевіреного корпусу</label>
          <div className="query"><input id="query" placeholder="Поставте питання…" /><button type="button">Знайти</button></div>
        </form>
      </section>
      <section className="grid" aria-label="Модулі">
        {domains.map(([title, body]) => <article key={title}><h2>{title}</h2><p>{body}</p><span>Відкрити →</span></article>)}
      </section>
      <aside><b>Принцип:</b> джерело важливіше за впевнений тон моделі.</aside>
    </main>
  );
}

