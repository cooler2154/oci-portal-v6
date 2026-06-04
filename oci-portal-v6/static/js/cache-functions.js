/* ─────────────────────────────────────────────────────────────────────────
   Cache Management Functions - JDE Clear Cache functionality
   ───────────────────────────────────────────────────────────────────────── */

/**
 * Clear cache for a specific JDE environment
 * @param {string} cacheName - Cache environment name (DV920, PY920, DM920)
 */
async function clearCache(cacheName) {
  const btn = document.getElementById(`cache-btn-${cacheName}`);
  const resultDiv = document.getElementById(`cache-result-${cacheName}`);
  
  if (!btn || !resultDiv) {
    console.error(`Cache elements not found for ${cacheName}`);
    return;
  }

  // Disable button and show loading state
  const originalText = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i class="ti ti-loader-2" style="animation:spin 1s linear infinite;display:inline-block"></i> Processing...';
  resultDiv.innerHTML = '';

  try {
    const token = sessionStorage.getItem('token');
    if (!token) {
      throw new Error('Authentication token not found. Please log in again.');
    }

    const response = await fetch(`/api/clearCaches/${cacheName}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      }
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || data.error || `Failed to clear ${cacheName} cache`);
    }

    // Display success message with results
    let html = `<div style="color:var(--green);font-size:11px;font-weight:600;padding:8px;background:rgba(34,197,94,0.1);border-radius:4px;border:1px solid rgba(34,197,94,0.3);margin-bottom:8px">
      <i class="ti ti-check"></i> ${data.message}
    </div>`;
    
    if (data.results && data.results.length > 0) {
      html += '<div style="font-size:10px;color:var(--text-3)">';
      data.results.forEach(result => {
        const statusColor = result.status >= 200 && result.status < 300 ? '#22c55e' : '#dc3545';
        const statusIcon = result.status >= 200 && result.status < 300 ? 'ti-check-circle' : 'ti-alert-circle';
        html += `<div style="margin:4px 0;display:flex;align-items:center;gap:6px">
          <i class="ti ${statusIcon}" style="color:${statusColor};min-width:16px"></i>
          <span><strong>${result.path}</strong> (${result.status})</span>
        </div>`;
      });
      html += '</div>';
    }

    resultDiv.innerHTML = html;
    showToast(`✓ Cache ${cacheName} cleared successfully`, 'success');
    console.log(`Cache ${cacheName} cleared:`, data);

  } catch (error) {
    console.error(`Cache clear error for ${cacheName}:`, error);
    resultDiv.innerHTML = `<div style="color:var(--red);font-size:11px;font-weight:600;padding:8px;background:rgba(220,38,38,0.1);border-radius:4px;border:1px solid rgba(220,38,38,0.3)">
      <i class="ti ti-alert-circle"></i> ${error.message}
    </div>`;
    showToast(`✗ Error: ${error.message}`, 'error');

  } finally {
    // Re-enable button
    btn.disabled = false;
    btn.innerHTML = originalText;
  }
}

/**
 * Open cache configuration modal (admin only)
 */
function openCacheConfig() {
  const user = JSON.parse(sessionStorage.getItem('currentUser') || '{}');
  if (user.role !== 'admin') {
    showToast('Only admins can configure cache settings', 'warning');
    return;
  }
  // TODO: Implement cache configuration modal for updating CACHE_CONFIG
  showToast('Cache configuration UI coming soon', 'info');
}

/**
 * Initialize cache tab on page load
 */
function initCacheTab() {
  const cacheButtons = document.querySelectorAll('.btn-cache');
  cacheButtons.forEach(btn => {
    if (!btn.dataset.initialized) {
      // Add hover effects dynamically
      btn.addEventListener('mouseenter', function() {
        if (!this.disabled) {
          this.style.opacity = '0.9';
          this.style.transform = 'scale(1.02)';
        }
      });
      btn.addEventListener('mouseleave', function() {
        this.style.opacity = '1';
        this.style.transform = 'scale(1)';
      });
      btn.dataset.initialized = 'true';
    }
  });
}

// Initialize cache functions when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initCacheTab);
} else {
  initCacheTab();
}
