/**
 * Shared date validation utility functions
 */

function validateDateRange(startDateInput, endDateInput, options = {}) {
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    // Convert dates for comparison
    const startDate = startDateInput.value ? new Date(startDateInput.value + 'T00:00:00') : null;
    const endDate = endDateInput.value ? new Date(endDateInput.value + 'T00:00:00') : null;

    // Reset previous validation messages
    startDateInput.setCustomValidity('');
    endDateInput.setCustomValidity('');

    let isValid = true;

    // Validate future dates
    if (startDate && startDate > today) {
        startDateInput.setCustomValidity('Date cannot be in the future');
        isValid = false;
    }

    if (endDate && endDate > today) {
        endDateInput.setCustomValidity('Date cannot be in the future');
        isValid = false;
    }

    // Validate date range if both dates are set
    if (startDate && endDate && endDate < startDate) {
        endDateInput.setCustomValidity('End date cannot be before start date');
        isValid = false;
    }

    // Show validation messages if there are errors
    if (!isValid) {
        if (startDateInput.validationMessage) {
            startDateInput.reportValidity();
        }
        if (endDateInput.validationMessage) {
            endDateInput.reportValidity();
        }
    }

    return isValid;
}

function initializeDateRangeValidation(formId, startDateId, endDateId) {
    const form = document.getElementById(formId);
    const startDateInput = document.getElementById(startDateId);
    const endDateInput = document.getElementById(endDateId);

    if (!form || !startDateInput || !endDateInput) return;

    // Set max date to today
    const today = new Date().toISOString().split('T')[0];
    startDateInput.max = today;
    endDateInput.max = today;

    // Update min date for end date input when start date changes
    startDateInput.addEventListener('change', () => {
        endDateInput.min = startDateInput.value;
        validateDateRange(startDateInput, endDateInput);
    });

    // Validate when end date changes
    endDateInput.addEventListener('change', () => {
        validateDateRange(startDateInput, endDateInput);
    });

    // Validate on form submission
    form.addEventListener('submit', (event) => {
        if (!validateDateRange(startDateInput, endDateInput)) {
            event.preventDefault();
        }
    });
}