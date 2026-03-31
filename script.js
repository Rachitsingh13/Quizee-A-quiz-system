// Essential JavaScript functions for Quiz Platform

// Copy quiz link to clipboard
function copyQuizLink(shareCode) {
    const link = window.location.origin + '/quiz/' + shareCode;
    navigator.clipboard.writeText(link).then(() => {
        alert('Quiz link copied to clipboard!');
    });
}

// Auto-resize textareas
document.addEventListener('DOMContentLoaded', function() {
    const textareas = document.querySelectorAll('textarea');
    textareas.forEach(textarea => {
        textarea.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = this.scrollHeight + 'px';
        });
    });
});
