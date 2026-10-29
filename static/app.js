const instrumentSelect = document.querySelector('#instrument-select');
const instrumentUnit = document.querySelector('#shipment-unit');
const shipmentForm = document.querySelector('#shipment-form');
const shipmentId = document.querySelector('#shipment-id');
const shipmentList = document.querySelector('#shipment-list');
const statusMessage = document.querySelector('#status-message');
const instrumentList = document.querySelector('#instrument-list');
let instruments = [];

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  });
  if (response.status === 204) return null;
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'No se pudo completar la operación.');
  return body;
}

function showStatus(message, isError = false) {
  statusMessage.textContent = message;
  statusMessage.classList.toggle('error', isError);
}

function addCell(row, text, className = '') {
  const cell = document.createElement('td');
  cell.textContent = text;
  if (className) cell.className = className;
  row.append(cell);
  return cell;
}

async function loadInstruments(selectedId = '') {
  instruments = await api('/api/instrumentos');
  instrumentSelect.replaceChildren();
  instrumentList.replaceChildren();
  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = instruments.length ? 'Seleccionar instrumento' : 'Agregá un instrumento primero';
  instrumentSelect.append(placeholder);
  if (!instruments.length) {
    const empty = document.createElement('li');
    empty.className = 'empty-state';
    empty.textContent = 'Todavía no hay instrumentos.';
    instrumentList.append(empty);
  }
  for (const instrument of instruments) {
    const option = document.createElement('option');
    option.value = instrument.id;
    option.textContent = `${instrument.nombre} · ${instrument.etiqueta_octal}`;
    option.dataset.unit = instrument.unidad;
    instrumentSelect.append(option);

    const item = document.createElement('li');
    const details = document.createElement('span');
    details.textContent = `${instrument.nombre} · ${instrument.valor_minimo} a ${instrument.valor_maximo} ${instrument.unidad}`;
    const actions = document.createElement('span');
    actions.className = 'instrument-actions';
    actions.append(
      makeAction('Editar', () => beginInstrumentEdit(instrument)),
      makeAction('Eliminar', () => deleteInstrument(instrument.id), 'delete'),
    );
    item.append(details, actions);
    instrumentList.append(item);
  }
  instrumentSelect.value = selectedId;
  instrumentUnit.value = instrumentSelect.selectedOptions[0]?.dataset.unit || '';
}

function makeAction(label, action, className = '') {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = label;
  if (className) button.className = className;
  button.addEventListener('click', action);
  return button;
}

async function loadShipments() {
  const shipments = await api('/api/envios');
  document.querySelector('#shipment-count').textContent = shipments.length;
  shipmentList.replaceChildren();
  if (!shipments.length) {
    const row = document.createElement('tr');
    const empty = addCell(row, 'Todavía no hay envíos registrados.', 'empty-state');
    empty.colSpan = 6;
    shipmentList.append(row);
    return;
  }

  for (const shipment of [...shipments].reverse()) {
    const row = document.createElement('tr');
    addCell(row, shipment.instrumento.nombre);
    addCell(row, `${shipment.valor} ${shipment.instrumento.unidad}`.trim(), 'value-cell');
    addCell(row, shipment.instrumento.etiqueta_octal);
    const wordCell = addCell(row, '');
    const word = document.createElement('code');
    word.className = 'word-bits';
    word.textContent = shipment.palabra_arinc_bits;
    word.title = shipment.palabra_arinc_hex;
    wordCell.append(word);
    const date = new Date(shipment.creado_en);
    addCell(row, Number.isNaN(date.valueOf()) ? shipment.creado_en : date.toLocaleString('es-AR'), 'date-cell');
    const actions = addCell(row, '', 'actions');
    actions.append(
      makeAction('Transmitir', () => transmitShipment(shipment.id)),
      makeAction('Editar', () => beginEdit(shipment)),
      makeAction('Eliminar', () => deleteShipment(shipment.id), 'delete'),
    );
    shipmentList.append(row);
  }
}

function beginInstrumentEdit(instrument) {
  document.querySelector('#instrument-id').value = instrument.id;
  document.querySelector('#instrument-name').value = instrument.nombre;
  document.querySelector('#instrument-label').value = instrument.etiqueta_octal;
  document.querySelector('#instrument-resolution').value = instrument.resolucion;
  document.querySelector('#instrument-minimum').value = instrument.valor_minimo;
  document.querySelector('#instrument-maximum').value = instrument.valor_maximo;
  document.querySelector('#instrument-unit').value = instrument.unidad;
  document.querySelector('#submit-instrument').textContent = 'Guardar cambios';
  document.querySelector('#cancel-instrument-edit').hidden = false;
  document.querySelector('#instrument-name').focus();
}

function resetInstrumentForm() {
  document.querySelector('#instrument-form').reset();
  document.querySelector('#instrument-id').value = '';
  document.querySelector('#submit-instrument').textContent = 'Guardar instrumento';
  document.querySelector('#cancel-instrument-edit').hidden = true;
}

async function deleteInstrument(id) {
  if (!window.confirm('¿Eliminar este instrumento? No se pueden eliminar instrumentos con envíos registrados.')) return;
  try {
    await api(`/api/instrumentos/${id}`, { method: 'DELETE' });
    if (Number(instrumentSelect.value) === id) instrumentSelect.value = '';
    await loadInstruments(instrumentSelect.value);
    showStatus('Instrumento eliminado.');
  } catch (error) {
    showStatus(error.message, true);
  }
}

async function transmitShipment(id) {
  try {
    const result = await api(`/api/envios/${id}/transmitir`, { method: 'POST' });
    showStatus(`${result.mensaje} ${result.palabra_arinc_hex}`);
  } catch (error) {
    showStatus(error.message, true);
  }
}

function beginEdit(shipment) {
  shipmentId.value = shipment.id;
  instrumentSelect.value = shipment.instrumento.id;
  instrumentUnit.value = shipment.instrumento.unidad || '';
  document.querySelector('#shipment-value').value = shipment.valor;
  document.querySelector('#shipment-sdi').value = shipment.sdi;
  document.querySelector('#shipment-ssm').value = shipment.ssm;
  document.querySelector('#submit-shipment').firstChild.textContent = 'Guardar cambios ';
  document.querySelector('#cancel-edit').hidden = false;
  document.querySelector('#shipment-value').focus();
}

function resetShipmentForm() {
  shipmentForm.reset();
  shipmentId.value = '';
  document.querySelector('#submit-shipment').firstChild.textContent = 'Crear envío ';
  document.querySelector('#cancel-edit').hidden = true;
  instrumentUnit.value = instrumentSelect.selectedOptions[0]?.dataset.unit || '';
}

async function deleteShipment(id) {
  if (!window.confirm('¿Eliminar este envío del historial?')) return;
  try {
    await api(`/api/envios/${id}`, { method: 'DELETE' });
    showStatus('Envío eliminado.');
    await loadShipments();
  } catch (error) {
    showStatus(error.message, true);
  }
}

instrumentSelect.addEventListener('change', () => {
  instrumentUnit.value = instrumentSelect.selectedOptions[0]?.dataset.unit || '';
});

shipmentForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const id = shipmentId.value;
  const payload = {
    instrumento_id: Number(instrumentSelect.value),
    valor: Number(document.querySelector('#shipment-value').value),
    sdi: Number(document.querySelector('#shipment-sdi').value),
    ssm: Number(document.querySelector('#shipment-ssm').value),
  };
  try {
    await api(id ? `/api/envios/${id}` : '/api/envios', {
      method: id ? 'PUT' : 'POST',
      body: JSON.stringify(payload),
    });
    resetShipmentForm();
    showStatus(id ? 'Cambios guardados.' : 'Envío creado.');
    await loadShipments();
  } catch (error) {
    showStatus(error.message, true);
  }
});

document.querySelector('#cancel-edit').addEventListener('click', resetShipmentForm);
document.querySelector('#refresh-button').addEventListener('click', async () => {
  try {
    await Promise.all([loadInstruments(instrumentSelect.value), loadShipments()]);
    showStatus('Historial actualizado.');
  } catch (error) {
    showStatus(error.message, true);
  }
});

document.querySelector('#instrument-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const id = document.querySelector('#instrument-id').value;
  const payload = {
    nombre: document.querySelector('#instrument-name').value.trim(),
    etiqueta_octal: document.querySelector('#instrument-label').value.trim(),
    resolucion: Number(document.querySelector('#instrument-resolution').value),
    valor_minimo: Number(document.querySelector('#instrument-minimum').value),
    valor_maximo: Number(document.querySelector('#instrument-maximum').value),
    unidad: document.querySelector('#instrument-unit').value.trim(),
  };
  try {
    const saved = await api(id ? `/api/instrumentos/${id}` : '/api/instrumentos', {
      method: id ? 'PUT' : 'POST',
      body: JSON.stringify(payload),
    });
    resetInstrumentForm();
    await Promise.all([loadInstruments(saved.id), loadShipments()]);
    showStatus(id ? 'Instrumento actualizado.' : 'Instrumento agregado.');
  } catch (error) {
    showStatus(error.message, true);
  }
});

document.querySelector('#cancel-instrument-edit').addEventListener('click', resetInstrumentForm);

Promise.all([loadInstruments(), loadShipments()]).catch((error) => showStatus(error.message, true));
