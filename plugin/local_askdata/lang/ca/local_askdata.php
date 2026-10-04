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
 * Catalan strings for local_askdata.
 *
 * @package    local_askdata
 * @copyright  2026 Antoni Bertran
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

defined('MOODLE_INTERNAL') || die();

$string['askdata:ask'] = 'Fer preguntes sobre les dades del curs';
$string['askyourdata'] = 'Pregunta a les teves dades';
$string['elapsed'] = '{$a} ms';
$string['error_badresponse'] = 'El servei d\'analítica ha enviat una resposta que no es pot llegir. Torneu-ho a provar.';
$string['error_emptyquestion'] = 'Escriviu primer una pregunta.';
$string['error_notconfigured'] = 'El servei d\'analítica encara no està configurat. Demaneu a l\'administrador del lloc que indiqui l\'URL del servei i el secret compartit.';
$string['error_service'] = 'El servei d\'analítica no ha pogut respondre aquesta pregunta: {$a}';
$string['error_service_generic'] = 'El servei d\'analítica no ha pogut respondre aquesta pregunta. Torneu-ho a provar o reformuleu-la.';
$string['error_signature'] = 'Moodle i el servei d\'analítica no s\'han pogut verificar mútuament. Demaneu a l\'administrador del lloc que revisi el secret compartit i l\'hora dels servidors.';
$string['error_unreachable'] = 'El servei d\'analítica no està disponible en aquest moment. Torneu-ho a provar més tard.';
$string['eventquestionasked'] = 'Pregunta enviada al servei d\'analítica';
$string['example1'] = 'Quins cursos imparteixo i quants estudiants hi ha a cadascun?';
$string['example2'] = 'Quins estudiants no han accedit en els darrers 14 dies?';
$string['example3'] = 'Qui no ha lliurat la tasca que venç aquesta setmana?';
$string['example4'] = 'Quina és la qualificació mitjana de cada element qualificable del meu curs?';
$string['example5'] = 'Quina activitat té el major abandonament?';
$string['example6'] = 'Compara la finalització entre els meus cursos i explica les diferències';
$string['examples'] = 'Proveu una d\'aquestes preguntes';
$string['history'] = 'Preguntes anteriors';
$string['intro'] = 'Feu una pregunta en llenguatge natural sobre els cursos que impartiu. La resposta es calcula als servidors propis de l\'organització, només amb dades pseudonimitzades.';
$string['maxrows'] = 'Nombre màxim de files';
$string['maxrows_desc'] = 'Nombre màxim de files que es demanen al servei d\'analítica i es mostren en una resposta. El servei aplica el menor entre aquest valor i el seu propi límit.';
$string['noresults'] = 'La consulta s\'ha executat però no ha retornat cap fila.';
$string['pluginname'] = 'Pregunta a les teves dades';
$string['privacy:metadata:analytics_service'] = 'Les preguntes s\'envien al servei d\'analítica configurat per l\'administrador del lloc, que funciona a la infraestructura pròpia de l\'organització. No s\'envien noms ni adreces de correu.';
$string['privacy:metadata:analytics_service:course_ids'] = 'Els identificadors dels cursos que l\'usuari pot analitzar, per limitar la resposta a aquests cursos.';
$string['privacy:metadata:analytics_service:question'] = 'La pregunta escrita per l\'usuari.';
$string['privacy:metadata:analytics_service:user_ref'] = 'Una referència pseudònima derivada de l\'identificador de l\'usuari amb un hash amb clau. No es pot tornar a convertir en l\'identificador sense el secret compartit.';
$string['question'] = 'La vostra pregunta';
$string['questionplaceholder'] = 'Per exemple: quins estudiants no han accedit en els darrers 14 dies?';
$string['rowcount'] = '{$a} files';
$string['send'] = 'Envia';
$string['sending'] = 'Pensant...';
$string['serviceurl'] = 'URL del servei d\'analítica';
$string['serviceurl_desc'] = 'URL base del servei d\'analítica, sense el camí /ask. Moodle el crida des del servidor, mai des del navegador. Comproveu que l\'amfitrió no és a la llista d\'amfitrions bloquejats de cURL i que el seu port és als ports permesos de cURL.';
$string['sharedsecret'] = 'Secret compartit';
$string['sharedsecret_desc'] = 'Secret compartit amb el servei d\'analítica. Signa cada petició (HMAC-SHA256) i genera la referència pseudònima de l\'usuari. Ha de coincidir amb ASKDATA_SHARED_SECRET al servei.';
$string['sql'] = 'SQL generat';
$string['timeout'] = 'Temps d\'espera (segons)';
$string['timeout_desc'] = 'Temps màxim d\'espera d\'una resposta. Els models locals poden trigar en la primera pregunta.';
$string['truncated'] = 'Només es mostren les primeres {$a} files.';
