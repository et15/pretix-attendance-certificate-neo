// Keeps a rejected rename in the layout editor from costing unsaved work.
// Kept as a static file (not an inline <script>): pretix's Content-Security-Policy
// only allows scripts served from its static domain.
//
// pretix's editor shows only "Saving failed." for an error response and leaves
// the save button disabled, so the page would have to be reloaded (losing all
// unsaved edits). Therefore:
// 1. Names known to be taken are caught before saving (this handler is bound
//    before pretix's editor binds its own, and stops it).
// 2. If the server still rejects the name (e.g. someone else took it
//    meanwhile), the save button is re-enabled so the user can rename and save
//    again.
(function ($) {
    var dataEl = document.getElementById("attendance-certificate-name-check");
    var $name = $("#pdf-info-name");
    var $save = $("#editor-save");
    if (!dataEl || !$name.length || !$save.length) {
        return;
    }
    var config = JSON.parse(dataEl.textContent);
    var $help = $('<p class="help-block" id="attendance-certificate-name-error"></p>').hide();
    $name.after($help);

    function key(value) {
        return (value || "").trim().toLowerCase();
    }

    function showError(message) {
        $name.closest(".control-group").addClass("has-error");
        $help.text(message).show();
    }

    function clearError() {
        $name.closest(".control-group").removeClass("has-error");
        $help.hide();
    }

    function isTaken() {
        return config.taken.indexOf(key($name.val())) !== -1;
    }

    $name.on("input change", function () {
        if (isTaken()) {
            showError(config.message);
        } else {
            clearError();
        }
    });

    $save.on("click", function (e) {
        if (isTaken()) {
            e.preventDefault();
            e.stopImmediatePropagation();
            showError(config.message);
            $name.trigger("focus");
            return false;
        }
    });

    $(document).ajaxSuccess(function (event, xhr, settings, data) {
        if (data && data.status === "error" && data.error_code === "name_taken") {
            config.taken.push(key($name.val()));
            showError(data.error);
            $save.prop("disabled", false)
                .removeClass("btn-success").addClass("btn-primary")
                .find(".fa").attr("class", "fa fa-fw fa-save");
        }
    });
})(jQuery);
