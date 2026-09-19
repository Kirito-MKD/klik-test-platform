/* Немного поведения, которого нет в HTML.

   Обходимся без библиотек: здесь три маленьких обработчика на делегировании
   событий, каждый работает сам по себе.
   Без скрипта страницы остаются рабочими: промпт можно выделить и скопировать
   руками, вариантов ответа изначально хватает на обычный вопрос, а удаление
   просто произойдёт без переспроса. */

(function () {
  "use strict";

  /* Копирование промпта и образца файла. */
  function copyText(button) {
    var source = document.querySelector(button.dataset.copy);
    if (!source) {
      return;
    }
    var text = source.innerText;
    var done = function () {
      var label = button.textContent;
      button.textContent = "Скопировано";
      button.disabled = true;
      window.setTimeout(function () {
        button.textContent = label;
        button.disabled = false;
      }, 2000);
    };

    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, function () {
        selectText(source);
      });
      return;
    }
    // Старый браузер или страница не по https: выделяем текст, дальше Ctrl+C.
    selectText(source);
  }

  function selectText(node) {
    var range = document.createRange();
    range.selectNodeContents(node);
    var selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }

  /* Ещё одна строка варианта ответа.

     Формсет Django считает строки по полю TOTAL_FORMS, а в заготовке вместо
     номера стоит __prefix__ — его и подставляем. */
  function addRow(button) {
    var container = document.querySelector(button.dataset.addRow);
    var template = document.getElementById("option-row-template");
    var total = document.getElementById("id_options-TOTAL_FORMS");
    var max = document.getElementById("id_options-MAX_NUM_FORMS");
    if (!container || !template || !total) {
      return;
    }

    var index = parseInt(total.value, 10);
    if (max && max.value && index >= parseInt(max.value, 10)) {
      button.disabled = true;
      return;
    }

    var row = template.innerHTML.replace(/__prefix__/g, String(index));
    container.insertAdjacentHTML("beforeend", row);
    total.value = String(index + 1);

    var added = container.lastElementChild.querySelector("input[type='text'], textarea");
    if (added) {
      added.focus();
    }
  }

  document.addEventListener("click", function (event) {
    var copy = event.target.closest("[data-copy]");
    if (copy) {
      copyText(copy);
      return;
    }

    var add = event.target.closest("[data-add-row]");
    if (add) {
      addRow(add);
      return;
    }

    /* Переспрос перед тем, что нельзя отменить. */
    var confirmable = event.target.closest("[data-confirm]");
    if (confirmable && !window.confirm(confirmable.dataset.confirm)) {
      event.preventDefault();
    }
  });
})();
