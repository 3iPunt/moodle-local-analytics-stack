// This file is part of Moodle - https://moodle.org/
//
// Moodle is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// Moodle is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with Moodle.  If not, see <https://www.gnu.org/licenses/>.

/**
 * Chat UI for the "Ask your data" page.
 *
 * The browser only talks to Moodle. Moodle calls the analytics service server side.
 *
 * @module     local_askdata/chat
 * @copyright  2026 Antoni Bertran
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

import Ajax from 'core/ajax';
import Templates from 'core/templates';
import Notification from 'core/notification';
import {getString} from 'core/str';

const SELECTORS = {
    form: '[data-region="ask-form"]',
    question: '[data-region="question"]',
    send: '[data-action="send"]',
    spinner: '[data-region="spinner"]',
    sending: '[data-region="sending"]',
    formError: '[data-region="form-error"]',
    example: '[data-action="example"]',
    answers: '[data-region="answers"]',
    historyHeading: '[data-region="history-heading"]',
};

/**
 * Toggles the loading state of the form.
 *
 * @param {HTMLElement} root The page root element.
 * @param {boolean} loading Whether a request is in progress.
 */
const setLoading = (root, loading) => {
    root.querySelector(SELECTORS.send).disabled = loading;
    root.querySelector(SELECTORS.question).readOnly = loading;
    root.querySelector(SELECTORS.spinner).classList.toggle('d-none', !loading);
    root.querySelector(SELECTORS.sending).classList.toggle('d-none', !loading);
    root.setAttribute('aria-busy', loading ? 'true' : 'false');
};

/**
 * Shows or hides the inline form error.
 *
 * @param {HTMLElement} root The page root element.
 * @param {string|null} message The message, or null to hide it.
 */
const setFormError = (root, message) => {
    const alert = root.querySelector(SELECTORS.formError);
    alert.textContent = message || '';
    alert.classList.toggle('d-none', !message);
};

/**
 * Builds the result template context from a web service response.
 *
 * @param {string} question The question asked.
 * @param {Object} response The local_askdata_ask response.
 * @returns {Object}
 */
const buildContext = (question, response) => ({
    question,
    error: '',
    sql: response.sql,
    columns: response.columns,
    rows: response.rows.map((cells) => ({cells})),
    hasrows: response.rows.length > 0,
    rowcount: response.rows.length,
    // eslint-disable-next-line camelcase
    elapsed_ms: response.elapsed_ms,
    truncated: response.truncated,
});

/**
 * Renders one answer at the top of the history.
 *
 * @param {HTMLElement} root The page root element.
 * @param {Object} context The result template context.
 */
const prependAnswer = async(root, context) => {
    const {html, js} = await Templates.renderForPromise('local_askdata/result', context);
    Templates.prependNodeContents(root.querySelector(SELECTORS.answers), html, js);
    root.querySelector(SELECTORS.historyHeading).classList.remove('d-none');
};

/**
 * Whether an error came from this plugin and is safe to show inline.
 *
 * @param {Object} error The rejected Ajax error.
 * @returns {boolean}
 */
const isServiceError = (error) => !!error && typeof error.errorcode === 'string' &&
    error.errorcode.startsWith('error_') && typeof error.message === 'string';

/**
 * Sends a question and renders the answer.
 *
 * @param {HTMLElement} root The page root element.
 * @param {number} courseid The current course id.
 * @param {string} question The question.
 */
const ask = async(root, courseid, question) => {
    setFormError(root, null);
    setLoading(root, true);
    try {
        const response = await Ajax.call([{
            methodname: 'local_askdata_ask',
            args: {courseid, question},
        }])[0];
        await prependAnswer(root, buildContext(question, response));
        root.querySelector(SELECTORS.question).value = '';
    } catch (error) {
        if (isServiceError(error)) {
            await prependAnswer(root, {question, error: error.message}).catch(Notification.exception);
        } else {
            Notification.exception(error);
        }
    } finally {
        setLoading(root, false);
        root.querySelector(SELECTORS.question).focus();
    }
};

/**
 * Initialises the chat page.
 *
 * @param {number} courseid The current course id.
 */
export const init = (courseid) => {
    const root = document.querySelector(`[data-region="local-askdata"][data-courseid="${Number(courseid)}"]`);
    if (!root || root.dataset.initialised) {
        return;
    }
    root.dataset.initialised = '1';

    const form = root.querySelector(SELECTORS.form);
    const textarea = root.querySelector(SELECTORS.question);

    form.addEventListener('submit', async(e) => {
        e.preventDefault();
        const question = textarea.value.trim();
        if (!question) {
            setFormError(root, await getString('error_emptyquestion', 'local_askdata'));
            return;
        }
        if (root.querySelector(SELECTORS.send).disabled) {
            return;
        }
        await ask(root, Number(courseid), question);
    });

    textarea.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            form.requestSubmit();
        }
    });

    root.addEventListener('click', (e) => {
        const example = e.target.closest(SELECTORS.example);
        if (!example) {
            return;
        }
        textarea.value = example.dataset.question;
        setFormError(root, null);
        textarea.focus();
    });
};
