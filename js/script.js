document.getElementById('year').textContent = new Date().getFullYear();

const formatter = new Intl.NumberFormat('es-CO', {
    style: 'currency',
    currency: 'COP',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0
});

const productGrid = document.getElementById('product-grid');
const emptyState = document.getElementById('empty-state');
const appMessage = document.getElementById('app-message');
const addForm = document.getElementById('add-form');
const addModal = document.getElementById('add-modal');
const formMessage = document.getElementById('form-message');
const saveButton = document.getElementById('btn-save-product');

async function readApiResponse(response) {
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
        throw new Error('No se pudo conectar con BETANA. Inicia el servidor con .\\run.ps1 y abre http://localhost:8000 (no abras index.html directamente).');
    }

    return response.json();
}

document.getElementById('btn-open-modal').addEventListener('click', () => {
    formMessage.textContent = '';
    formMessage.classList.add('hidden');
    addModal.classList.remove('hidden');
    setTimeout(() => addModal.classList.remove('opacity-0'), 10);
    document.body.style.overflow = 'hidden';
});

document.getElementById('btn-close-modal').addEventListener('click', closeAddModal);

function closeAddModal() {
    addModal.classList.add('opacity-0');
    setTimeout(() => {
        addModal.classList.add('hidden');
        document.body.style.overflow = 'auto';
    }, 300);
}

function renderInventory(inventory) {
    productGrid.replaceChildren();

    if (inventory.length === 0) {
        emptyState.classList.remove('hidden');
        return;
    }

    emptyState.classList.add('hidden');

    inventory.forEach(item => {
        const card = document.createElement('article');
        card.className = 'group flex flex-col relative';

        const imageContainer = document.createElement('div');
        imageContainer.className = 'relative w-full aspect-[2/3] bg-gray-50 overflow-hidden';

        const image = document.createElement('img');
        image.src = item.img;
        image.alt = item.name;
        image.className = 'w-full h-full object-cover';
        image.loading = 'lazy';
        imageContainer.appendChild(image);

        const overlay = document.createElement('div');
        overlay.className = 'absolute inset-0 bg-black/5 opacity-0 group-hover:opacity-100 transition-opacity duration-300';
        imageContainer.appendChild(overlay);

        const details = document.createElement('div');
        details.className = 'flex flex-col mt-3 mb-6 px-1';

        const name = document.createElement('h2');
        name.className = 'text-micro uppercase truncate';
        name.textContent = item.name;

        const price = document.createElement('p');
        price.className = 'text-micro text-gray-600 mt-1';
        price.textContent = `${formatter.format(item.price)} COP`;

        details.append(name, price);
        card.append(imageContainer, details);
        productGrid.appendChild(card);
    });
}

async function loadInventory() {
    try {
        const response = await fetch('/api/products', {
            headers: { Accept: 'application/json' }
        });
        const inventory = await readApiResponse(response);

        if (!response.ok) {
            throw new Error(inventory.error || 'No se pudo consultar el catálogo.');
        }

        renderInventory(inventory);
    } catch (error) {
        appMessage.textContent = `No se pudo cargar el catálogo: ${error.message}`;
        appMessage.classList.remove('hidden');
    }
}

addForm.addEventListener('submit', async event => {
    event.preventDefault();
    formMessage.textContent = '';
    formMessage.classList.add('hidden');
    saveButton.disabled = true;
    saveButton.textContent = 'Guardando…';

    try {
        const response = await fetch('/api/products', {
            method: 'POST',
            headers: { Accept: 'application/json' },
            body: new FormData(addForm)
        });
        const body = await readApiResponse(response);

        if (!response.ok) {
            throw new Error(body.error || 'No se pudo guardar el producto.');
        }

        addForm.reset();
        closeAddModal();
        renderInventory(body);
        appMessage.textContent = 'Artículo añadido al catálogo.';
        appMessage.classList.remove('hidden', 'text-red-600');
        appMessage.classList.add('text-gray-600');
    } catch (error) {
        formMessage.textContent = error.message;
        formMessage.classList.remove('hidden');
    } finally {
        saveButton.disabled = false;
        saveButton.textContent = 'Guardar artículo';
    }
});

window.addEventListener('DOMContentLoaded', loadInventory);
