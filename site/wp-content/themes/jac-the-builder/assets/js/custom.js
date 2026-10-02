jQuery(document).ready(function () {

    var lastScroll = 0;
    var header = jQuery('.fusion-header-wrapper');
    var headerHeight = header.outerHeight();
    
    jQuery(window).scroll(function() {
        var currentScroll = jQuery(this).scrollTop();
        
        // Only show header when scrolling up
        if (currentScroll < lastScroll && currentScroll > headerHeight) {
            // Scrolling up
            header.addClass('fusion-is-sticky').removeClass('fusion-sticky-hidden');
        } else {
            // Scrolling down
            if (currentScroll > headerHeight) {
                header.removeClass('fusion-is-sticky').addClass('fusion-sticky-hidden');
            }
        }
        
        // At top of page
        if (currentScroll <= headerHeight) {
            header.removeClass('fusion-is-sticky fusion-sticky-hidden');
        }
        
        lastScroll = currentScroll;
    });




});