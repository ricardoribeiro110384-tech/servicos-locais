from api.profissional import handler as ProfessionalHandler


class handler(ProfessionalHandler):
    # Preserve the former endpoint as an alias for the single account flow.
    def do_POST(self):
        super().do_POST()
