<?php
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
 * Spanish strings for local_askdata.
 *
 * @package    local_askdata
 * @copyright  2026 Antoni Bertran
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

defined('MOODLE_INTERNAL') || die();

$string['askdata:ask'] = 'Hacer preguntas sobre los datos del curso';
$string['askyourdata'] = 'Pregunta a tus datos';
$string['elapsed'] = '{$a} ms';
$string['error_badresponse'] = 'El servicio de analítica ha enviado una respuesta que no se puede leer. Inténtelo de nuevo.';
$string['error_emptyquestion'] = 'Escriba primero una pregunta.';
$string['error_notconfigured'] = 'El servicio de analítica todavía no está configurado. Pida al administrador del sitio que indique la URL del servicio y el secreto compartido.';
$string['error_service'] = 'El servicio de analítica no ha podido responder a esta pregunta: {$a}';
$string['error_service_generic'] = 'El servicio de analítica no ha podido responder a esta pregunta. Inténtelo de nuevo o reformúlela.';
$string['error_signature'] = 'Moodle y el servicio de analítica no han podido verificarse mutuamente. Pida al administrador del sitio que revise el secreto compartido y la hora de los servidores.';
$string['error_unreachable'] = 'El servicio de analítica no está disponible en este momento. Inténtelo más tarde.';
$string['eventquestionasked'] = 'Pregunta enviada al servicio de analítica';
$string['example1'] = '¿Qué cursos imparto y cuántos estudiantes hay en cada uno?';
$string['example2'] = '¿Qué estudiantes no han accedido en los últimos 14 días?';
$string['example3'] = '¿Quién no ha entregado la tarea que vence esta semana?';
$string['example4'] = '¿Cuál es la calificación media de cada elemento calificable de mi curso?';
$string['example5'] = '¿Qué actividad tiene el mayor abandono?';
$string['example6'] = 'Compara la finalización entre mis cursos y explica las diferencias';
$string['examples'] = 'Pruebe una de estas preguntas';
$string['history'] = 'Preguntas anteriores';
$string['intro'] = 'Haga una pregunta en lenguaje natural sobre los cursos que imparte. La respuesta se calcula en los servidores propios de la organización, solo con datos seudonimizados.';
$string['maxrows'] = 'Número máximo de filas';
$string['maxrows_desc'] = 'Número máximo de filas que se piden al servicio de analítica y se muestran en una respuesta. El servicio aplica el menor entre este valor y su propio límite.';
$string['noresults'] = 'La consulta se ha ejecutado pero no ha devuelto filas.';
$string['pluginname'] = 'Pregunta a tus datos';
$string['privacy:metadata:analytics_service'] = 'Las preguntas se envían al servicio de analítica configurado por el administrador del sitio, que funciona en la infraestructura propia de la organización. No se envían nombres ni direcciones de correo.';
$string['privacy:metadata:analytics_service:course_ids'] = 'Los identificadores de los cursos que el usuario puede analizar, para limitar la respuesta a esos cursos.';
$string['privacy:metadata:analytics_service:question'] = 'La pregunta escrita por el usuario.';
$string['privacy:metadata:analytics_service:user_ref'] = 'Una referencia seudónima derivada del identificador del usuario con un hash con clave. No se puede convertir de nuevo en el identificador sin el secreto compartido.';
$string['question'] = 'Su pregunta';
$string['questionplaceholder'] = 'Por ejemplo: ¿qué estudiantes no han accedido en los últimos 14 días?';
$string['rowcount'] = '{$a} filas';
$string['send'] = 'Enviar';
$string['sending'] = 'Pensando...';
$string['serviceurl'] = 'URL del servicio de analítica';
$string['serviceurl_desc'] = 'URL base del servicio de analítica, sin la ruta /ask. Moodle lo llama desde el servidor, nunca desde el navegador. Compruebe que el host no está en la lista de hosts bloqueados de cURL y que su puerto está en los puertos permitidos de cURL.';
$string['sharedsecret'] = 'Secreto compartido';
$string['sharedsecret_desc'] = 'Secreto compartido con el servicio de analítica. Firma cada petición (HMAC-SHA256) y genera la referencia seudónima del usuario. Debe coincidir con ASKDATA_SHARED_SECRET en el servicio.';
$string['sql'] = 'SQL generado';
$string['timeout'] = 'Tiempo de espera (segundos)';
$string['timeout_desc'] = 'Tiempo máximo de espera de una respuesta. Los modelos locales pueden tardar en la primera pregunta.';
$string['truncated'] = 'Solo se muestran las primeras {$a} filas.';
