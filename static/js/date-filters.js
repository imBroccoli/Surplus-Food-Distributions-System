/**
 * Initialize date filter validation for activity log filters
 */
function initializeDateFilters() {
    const dateFromInput = document.getElementById('date_from');
    const dateToInput = document.getElementById('date_to');
    const filterForm = document.querySelector('form');

    if (!dateFromInput || !dateToInput || !filterForm) return;

    // Set max date to today for both inputs
    const today = new Date().toISOString().split('T')[0];
    dateFromInput.max = today;
    dateToInput.max = today;

    // Update "Date To" min value when "Date From" changes
    dateFromInput.addEventListener('change', function () {
        dateToInput.min = this.value;
    });

    // Run initial setup
    if (dateFromInput.value) {
        dateToInput.min = dateFromInput.value;
    }
}