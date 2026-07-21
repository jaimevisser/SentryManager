function getDeletePrompt(selectionCount) {
    if (selectionCount === 1) {
        return {
            title: "Delete selected clip?",
            message: "This permanently deletes the selected clip from disk.",
            actionLabel: "Delete clip",
        };
    }

    return {
        title: `Delete ${selectionCount} selected clips?`,
        message: `This permanently deletes ${selectionCount} selected clips from disk.`,
        actionLabel: "Delete clips",
    };
}

function getPrompt(options) {
    if (options && typeof options === "object") {
        const title = typeof options.title === "string" ? options.title : "Confirm action?";
        const message = typeof options.message === "string" ? options.message : "";
        const actionLabel = typeof options.actionLabel === "string" ? options.actionLabel : "Confirm";
        return { title, message, actionLabel };
    }

    return getDeletePrompt(typeof options === "number" ? options : 1);
}

export function createDeleteModalController() {
    const deleteModal = document.querySelector("[data-index-delete-modal]");
    const deleteModalPanel = deleteModal?.querySelector(".selection-delete-modal-panel") || null;
    const deleteModalTitle = deleteModal?.querySelector("h2") || null;
    const deleteModalMessage = document.querySelector("[data-index-delete-message]");
    const deleteModalCancelButton = document.querySelector("[data-index-delete-cancel]");
    const deleteModalConfirmButton = document.querySelector("[data-index-delete-confirm]");

    function isOpen() {
        return Boolean(deleteModal?.open);
    }

    function show(options) {
        const prompt = getPrompt(options);

        if (!deleteModal || typeof deleteModal.showModal !== "function") {
            return Promise.resolve(window.confirm(prompt.title));
        }

        if (deleteModalTitle) {
            deleteModalTitle.textContent = prompt.title;
        }
        if (deleteModalMessage) {
            deleteModalMessage.textContent = prompt.message;
        }
        if (deleteModalConfirmButton) {
            deleteModalConfirmButton.textContent = prompt.actionLabel;
        }

        return new Promise((resolve) => {
            const handleClose = () => {
                resolve(deleteModal.returnValue === "confirm");
            };

            deleteModal.addEventListener("close", handleClose, { once: true });
            deleteModal.showModal();
            deleteModalCancelButton?.focus();
        });
    }

    deleteModal?.addEventListener("click", (event) => {
        if (!deleteModalPanel) {
            return;
        }

        const panelRect = deleteModalPanel.getBoundingClientRect();
        const clickedInsidePanel = (
            event.clientX >= panelRect.left
            && event.clientX <= panelRect.right
            && event.clientY >= panelRect.top
            && event.clientY <= panelRect.bottom
        );
        if (!clickedInsidePanel) {
            deleteModal.close("cancel");
        }
    });

    return { isOpen, show };
}