"""Notification text, per event, per locale.

`notification.locale` was captured on every row from the day the table existed
and never read, because the titles and bodies were English sentences written into
the call sites. Honouring it means the text has to live somewhere it can be looked
up, which is here.

The catalogue is deliberately flat data rather than a template engine. These are
short, fixed strings with named placeholders, the site already ships nine locales
through next-intl, and adding a second rendering system to the backend for nine
messages would be more machinery than the problem deserves.

Rules that keep this honest:

Every key must exist in every locale. A missing one is a caller falling back to
English silently, which is how a half-translated product happens; a test asserts
completeness rather than trusting it.

Placeholders are named and identical across locales for a key, so a translation
cannot quietly drop the order reference or the address that makes the message
useful. A test asserts that too.

Anything interpolated that a stranger controls, an organization name or a user
agent, is placed on its own line by the caller and marked unverified. Translating
a sentence does not make its contents trustworthy.
"""
from __future__ import annotations

from string import Formatter

# Mirrors apps/web/src/i18n/routing.ts. English is the fallback and must stay
# complete, since every lookup can land on it.
LOCALES = ("en", "es", "fr", "de", "pt", "ja", "ko", "zh", "ar")
FALLBACK = "en"

MESSAGES: dict[str, dict[str, tuple[str, str]]] = {
    "account.email_verification": {
        "en": (
            "Confirm your email address",
            "Open this link to confirm this address for your Agoreum account. It "
            "expires in 24 hours.\n\n{link}\n\nIf you did not request this, you can "
            "ignore it. Nothing changes until the link is opened.",
        ),
        "es": (
            "Confirma tu dirección de correo",
            "Abre este enlace para confirmar esta dirección en tu cuenta de Agoreum. "
            "Caduca en 24 horas.\n\n{link}\n\nSi no lo has solicitado, puedes "
            "ignorarlo. Nada cambia hasta que se abra el enlace.",
        ),
        "fr": (
            "Confirmez votre adresse e-mail",
            "Ouvrez ce lien pour confirmer cette adresse sur votre compte Agoreum. Il "
            "expire dans 24 heures.\n\n{link}\n\nSi vous n'êtes pas à l'origine de "
            "cette demande, ignorez ce message. Rien ne change tant que le lien n'est "
            "pas ouvert.",
        ),
        "de": (
            "Bestätigen Sie Ihre E-Mail-Adresse",
            "Öffnen Sie diesen Link, um diese Adresse für Ihr Agoreum-Konto zu "
            "bestätigen. Er läuft in 24 Stunden ab.\n\n{link}\n\nWenn Sie das nicht "
            "angefordert haben, ignorieren Sie diese Nachricht. Es ändert sich nichts, "
            "bis der Link geöffnet wird.",
        ),
        "pt": (
            "Confirme o seu endereço de email",
            "Abra esta ligação para confirmar este endereço na sua conta Agoreum. "
            "Expira em 24 horas.\n\n{link}\n\nSe não pediu isto, pode ignorar. Nada "
            "muda até a ligação ser aberta.",
        ),
        "ja": (
            "メールアドレスを確認してください",
            "このリンクを開いて、Agoreum アカウントのこのアドレスを確認してください。"
            "24時間で有効期限が切れます。\n\n{link}\n\n心当たりがない場合は無視して"
            "ください。リンクを開くまで何も変更されません。",
        ),
        "ko": (
            "이메일 주소를 확인하세요",
            "이 링크를 열어 Agoreum 계정의 이 주소를 확인하세요. 24시간 후 만료됩니다."
            "\n\n{link}\n\n요청하지 않았다면 무시해도 됩니다. 링크를 열기 전까지는 "
            "아무것도 변경되지 않습니다.",
        ),
        "zh": (
            "确认你的邮箱地址",
            "打开此链接以确认该地址用于你的 Agoreum 账户。链接将在 24 小时后失效。"
            "\n\n{link}\n\n如果这不是你发起的，可以忽略。在链接被打开之前不会有任何变化。",
        ),
        "ar": (
            "أكد عنوان بريدك الإلكتروني",
            "افتح هذا الرابط لتأكيد هذا العنوان لحسابك في Agoreum. تنتهي صلاحيته خلال "
            "24 ساعة.\n\n{link}\n\nإذا لم تطلب ذلك، يمكنك تجاهله. لا يتغير شيء حتى "
            "يُفتح الرابط.",
        ),
    },
    "account.new_signin": {
        "en": (
            "New sign-in to your Agoreum account",
            "Your wallet was used to sign in from {where}.\n\nThe device described "
            "itself as: {device}\nThat description comes from the software that signed "
            "in and is not verified.\n\nIf this was you, nothing further is needed. If "
            "it was not, disconnect the wallet and review your active sessions.",
        ),
        "es": (
            "Nuevo inicio de sesión en tu cuenta de Agoreum",
            "Se ha usado tu cartera para iniciar sesión desde {where}.\n\nEl "
            "dispositivo se identificó como: {device}\nEsa descripción proviene del "
            "software que inició sesión y no está verificada.\n\nSi has sido tú, no "
            "hace falta nada más. Si no, desconecta la cartera y revisa tus sesiones "
            "activas.",
        ),
        "fr": (
            "Nouvelle connexion à votre compte Agoreum",
            "Votre portefeuille a été utilisé pour se connecter depuis {where}.\n\nLe "
            "logiciel s'est décrit comme : {device}\nCette description provient du "
            "logiciel qui s'est connecté et n'est pas vérifiée.\n\nSi c'était vous, "
            "rien à faire. Sinon, déconnectez le portefeuille et vérifiez vos sessions "
            "actives.",
        ),
        "de": (
            "Neue Anmeldung bei Ihrem Agoreum-Konto",
            "Ihre Wallet wurde für eine Anmeldung von {where} verwendet.\n\nDas Gerät "
            "bezeichnete sich als: {device}\nDiese Beschreibung stammt von der Software, "
            "die sich angemeldet hat, und ist nicht überprüft.\n\nWaren Sie das, ist "
            "nichts weiter nötig. Andernfalls trennen Sie die Wallet und prüfen Sie "
            "Ihre aktiven Sitzungen.",
        ),
        "pt": (
            "Novo início de sessão na sua conta Agoreum",
            "A sua carteira foi usada para iniciar sessão a partir de {where}.\n\nO "
            "dispositivo identificou-se como: {device}\nEssa descrição vem do software "
            "que iniciou sessão e não é verificada.\n\nSe foi você, não é preciso mais "
            "nada. Caso contrário, desligue a carteira e reveja as sessões ativas.",
        ),
        "ja": (
            "Agoreum アカウントへの新しいサインイン",
            "{where} からウォレットを使用してサインインされました。\n\nデバイスの自己申告: "
            "{device}\nこの説明はサインインしたソフトウェアによるもので、検証されていません。"
            "\n\n心当たりがあれば対応は不要です。なければウォレットを切断し、有効な"
            "セッションを確認してください。",
        ),
        "ko": (
            "Agoreum 계정에 새로운 로그인",
            "{where} 에서 지갑으로 로그인했습니다.\n\n기기 자체 설명: {device}\n이 설명은 "
            "로그인한 소프트웨어가 제공한 것이며 검증되지 않았습니다.\n\n본인이라면 조치가 "
            "필요 없습니다. 아니라면 지갑 연결을 해제하고 활성 세션을 확인하세요.",
        ),
        "zh": (
            "你的 Agoreum 账户有新的登录",
            "你的钱包在 {where} 完成了一次登录。\n\n设备自述为：{device}\n该描述由登录的"
            "软件提供，未经验证。\n\n如果是你本人，无需处理。如果不是，请断开钱包连接并"
            "检查活动会话。",
        ),
        "ar": (
            "تسجيل دخول جديد إلى حسابك في Agoreum",
            "استُخدمت محفظتك لتسجيل الدخول من {where}.\n\nوصف الجهاز لنفسه: {device}\n"
            "هذا الوصف يأتي من البرنامج الذي سجّل الدخول وهو غير موثق.\n\nإن كان ذلك "
            "أنت، فلا حاجة لأي إجراء. وإن لم يكن، افصل المحفظة وراجع جلساتك النشطة.",
        ),
    },
    "order.funded": {
        "en": (
            "Order {reference} is funded and ready to start",
            "The buyer has funded escrow for order {reference}. Work can begin, and the "
            "delivery window has started.",
        ),
        "es": (
            "El pedido {reference} está financiado y listo para empezar",
            "El comprador ha financiado el depósito del pedido {reference}. Se puede "
            "empezar a trabajar y el plazo de entrega ha comenzado.",
        ),
        "fr": (
            "La commande {reference} est financée et peut démarrer",
            "L'acheteur a financé le séquestre de la commande {reference}. Le travail "
            "peut commencer et le délai de livraison a démarré.",
        ),
        "de": (
            "Bestellung {reference} ist finanziert und kann starten",
            "Der Käufer hat den Treuhandbetrag für Bestellung {reference} hinterlegt. "
            "Die Arbeit kann beginnen und die Lieferfrist läuft.",
        ),
        "pt": (
            "A encomenda {reference} está financiada e pronta a começar",
            "O comprador financiou a caução da encomenda {reference}. O trabalho pode "
            "começar e o prazo de entrega começou.",
        ),
        "ja": (
            "注文 {reference} の入金が完了し、開始できます",
            "購入者が注文 {reference} のエスクローに入金しました。作業を開始でき、"
            "納品期限が始まりました。",
        ),
        "ko": (
            "주문 {reference} 의 입금이 완료되어 시작할 수 있습니다",
            "구매자가 주문 {reference} 의 에스크로에 입금했습니다. 작업을 시작할 수 있으며 "
            "납품 기한이 시작되었습니다.",
        ),
        "zh": (
            "订单 {reference} 已托管付款，可以开始",
            "买家已为订单 {reference} 完成托管付款。可以开始工作，交付时限已开始计算。",
        ),
        "ar": (
            "الطلب {reference} ممول وجاهز للبدء",
            "قام المشتري بتمويل ضمان الطلب {reference}. يمكن بدء العمل، وقد بدأت مهلة "
            "التسليم.",
        ),
    },
    "order.released.buyer": {
        "en": (
            "Order {reference} has been paid out",
            "Escrow for order {reference} has been released to the provider.",
        ),
        "es": (
            "El pedido {reference} se ha pagado",
            "El depósito del pedido {reference} se ha liberado al proveedor.",
        ),
        "fr": (
            "La commande {reference} a été payée",
            "Le séquestre de la commande {reference} a été libéré au prestataire.",
        ),
        "de": (
            "Bestellung {reference} wurde ausgezahlt",
            "Der Treuhandbetrag für Bestellung {reference} wurde an den Anbieter "
            "freigegeben.",
        ),
        "pt": (
            "A encomenda {reference} foi paga",
            "A caução da encomenda {reference} foi libertada ao fornecedor.",
        ),
        "ja": (
            "注文 {reference} の支払いが完了しました",
            "注文 {reference} のエスクローが提供者に支払われました。",
        ),
        "ko": (
            "주문 {reference} 의 대금이 지급되었습니다",
            "주문 {reference} 의 에스크로가 제공자에게 지급되었습니다.",
        ),
        "zh": (
            "订单 {reference} 已完成付款",
            "订单 {reference} 的托管资金已释放给提供者。",
        ),
        "ar": (
            "تم دفع الطلب {reference}",
            "تم الإفراج عن ضمان الطلب {reference} للمزود.",
        ),
    },
    "order.released.provider": {
        "en": (
            "Order {reference} has been paid out",
            "Escrow for order {reference} has been released to you.",
        ),
        "es": (
            "El pedido {reference} se ha pagado",
            "El depósito del pedido {reference} se te ha liberado.",
        ),
        "fr": (
            "La commande {reference} a été payée",
            "Le séquestre de la commande {reference} vous a été libéré.",
        ),
        "de": (
            "Bestellung {reference} wurde ausgezahlt",
            "Der Treuhandbetrag für Bestellung {reference} wurde an Sie freigegeben.",
        ),
        "pt": (
            "A encomenda {reference} foi paga",
            "A caução da encomenda {reference} foi-lhe libertada.",
        ),
        "ja": (
            "注文 {reference} の支払いが完了しました",
            "注文 {reference} のエスクローがあなたに支払われました。",
        ),
        "ko": (
            "주문 {reference} 의 대금이 지급되었습니다",
            "주문 {reference} 의 에스크로가 귀하에게 지급되었습니다.",
        ),
        "zh": (
            "订单 {reference} 已完成付款",
            "订单 {reference} 的托管资金已释放给你。",
        ),
        "ar": (
            "تم دفع الطلب {reference}",
            "تم الإفراج عن ضمان الطلب {reference} لك.",
        ),
    },
    "order.refunded.buyer": {
        "en": (
            "Order {reference} has been refunded",
            "Escrow for order {reference} has been returned to you.",
        ),
        "es": (
            "El pedido {reference} se ha reembolsado",
            "El depósito del pedido {reference} se te ha devuelto.",
        ),
        "fr": (
            "La commande {reference} a été remboursée",
            "Le séquestre de la commande {reference} vous a été restitué.",
        ),
        "de": (
            "Bestellung {reference} wurde erstattet",
            "Der Treuhandbetrag für Bestellung {reference} wurde an Sie "
            "zurückgezahlt.",
        ),
        "pt": (
            "A encomenda {reference} foi reembolsada",
            "A caução da encomenda {reference} foi-lhe devolvida.",
        ),
        "ja": (
            "注文 {reference} が返金されました",
            "注文 {reference} のエスクローがあなたに返金されました。",
        ),
        "ko": (
            "주문 {reference} 이 환불되었습니다",
            "주문 {reference} 의 에스크로가 귀하에게 반환되었습니다.",
        ),
        "zh": (
            "订单 {reference} 已退款",
            "订单 {reference} 的托管资金已退还给你。",
        ),
        "ar": (
            "تم رد مبلغ الطلب {reference}",
            "تمت إعادة ضمان الطلب {reference} إليك.",
        ),
    },
    "order.refunded.provider": {
        "en": (
            "Order {reference} has been refunded",
            "Escrow for order {reference} has been returned to the buyer.",
        ),
        "es": (
            "El pedido {reference} se ha reembolsado",
            "El depósito del pedido {reference} se ha devuelto al comprador.",
        ),
        "fr": (
            "La commande {reference} a été remboursée",
            "Le séquestre de la commande {reference} a été restitué à l'acheteur.",
        ),
        "de": (
            "Bestellung {reference} wurde erstattet",
            "Der Treuhandbetrag für Bestellung {reference} wurde an den Käufer "
            "zurückgezahlt.",
        ),
        "pt": (
            "A encomenda {reference} foi reembolsada",
            "A caução da encomenda {reference} foi devolvida ao comprador.",
        ),
        "ja": (
            "注文 {reference} が返金されました",
            "注文 {reference} のエスクローが購入者に返金されました。",
        ),
        "ko": (
            "주문 {reference} 이 환불되었습니다",
            "주문 {reference} 의 에스크로가 구매자에게 반환되었습니다.",
        ),
        "zh": (
            "订单 {reference} 已退款",
            "订单 {reference} 的托管资金已退还给买家。",
        ),
        "ar": (
            "تم رد مبلغ الطلب {reference}",
            "تمت إعادة ضمان الطلب {reference} إلى المشتري.",
        ),
    },
    "order.disputed": {
        "en": (
            "A dispute was raised on order {reference}",
            "The other party has raised a dispute on order {reference}. An arbiter will "
            "review it. You can add context from the order page.",
        ),
        "es": (
            "Se ha abierto una disputa en el pedido {reference}",
            "La otra parte ha abierto una disputa en el pedido {reference}. Un árbitro "
            "la revisará. Puedes aportar contexto desde la página del pedido.",
        ),
        "fr": (
            "Un litige a été ouvert sur la commande {reference}",
            "L'autre partie a ouvert un litige sur la commande {reference}. Un arbitre "
            "l'examinera. Vous pouvez ajouter des éléments depuis la page de la "
            "commande.",
        ),
        "de": (
            "Zu Bestellung {reference} wurde ein Streitfall eröffnet",
            "Die Gegenseite hat zu Bestellung {reference} einen Streitfall eröffnet. Ein "
            "Schiedsrichter prüft ihn. Auf der Bestellseite können Sie Kontext "
            "ergänzen.",
        ),
        "pt": (
            "Foi aberta uma disputa na encomenda {reference}",
            "A outra parte abriu uma disputa na encomenda {reference}. Um árbitro irá "
            "analisá-la. Pode acrescentar contexto na página da encomenda.",
        ),
        "ja": (
            "注文 {reference} について異議が申し立てられました",
            "相手方が注文 {reference} について異議を申し立てました。仲裁者が確認します。"
            "注文ページから状況を補足できます。",
        ),
        "ko": (
            "주문 {reference} 에 분쟁이 제기되었습니다",
            "상대방이 주문 {reference} 에 분쟁을 제기했습니다. 중재자가 검토합니다. 주문 "
            "페이지에서 설명을 추가할 수 있습니다.",
        ),
        "zh": (
            "订单 {reference} 被提出争议",
            "对方对订单 {reference} 提出了争议。仲裁方将进行审核。你可以在订单页面补充说明。",
        ),
        "ar": (
            "تم فتح نزاع بشأن الطلب {reference}",
            "قام الطرف الآخر بفتح نزاع بشأن الطلب {reference}. سيراجعه محكّم. يمكنك "
            "إضافة توضيحات من صفحة الطلب.",
        ),
    },
    "order.dispute_decided": {
        "en": (
            "A decision has been made on order {reference}",
            "The dispute on order {reference} has been decided. The order page shows "
            "the split and the reasoning behind it. Funds move when the settlement "
            "is submitted on chain.",
        ),
        "es": (
            "Se ha tomado una decisión sobre el pedido {reference}",
            "La disputa del pedido {reference} se ha resuelto. La página del pedido "
            "muestra el reparto y el razonamiento. Los fondos se mueven cuando la "
            "liquidación se envía en la cadena.",
        ),
        "fr": (
            "Une décision a été prise sur la commande {reference}",
            "Le litige sur la commande {reference} a été tranché. La page de la "
            "commande indique la répartition et le raisonnement. Les fonds sont "
            "déplacés lorsque le règlement est soumis sur la chaîne.",
        ),
        "de": (
            "Zu Bestellung {reference} wurde entschieden",
            "Der Streitfall zu Bestellung {reference} wurde entschieden. Die "
            "Bestellseite zeigt die Aufteilung und die Begründung. Die Mittel bewegen "
            "sich, sobald die Abwicklung on chain eingereicht wird.",
        ),
        "pt": (
            "Foi tomada uma decisão sobre a encomenda {reference}",
            "A disputa da encomenda {reference} foi decidida. A página da encomenda "
            "mostra a divisão e o raciocínio. Os fundos movem-se quando a liquidação "
            "for submetida na cadeia.",
        ),
        "ja": (
            "注文 {reference} について決定がなされました",
            "注文 {reference} の異議について決定が行われました。分配とその理由は注文"
            "ページで確認できます。資金はチェーン上で清算が送信された時点で移動します。",
        ),
        "ko": (
            "주문 {reference} 에 대한 결정이 내려졌습니다",
            "주문 {reference} 의 분쟁이 결정되었습니다. 분배 내역과 그 이유는 주문 "
            "페이지에서 확인할 수 있습니다. 자금은 체인에서 정산이 제출될 때 이동합니다.",
        ),
        "zh": (
            "订单 {reference} 已作出裁定",
            "订单 {reference} 的争议已裁定。订单页面显示分配方式及其理由。资金将在链上"
            "提交结算时转移。",
        ),
        "ar": (
            "تم اتخاذ قرار بشأن الطلب {reference}",
            "تم البت في النزاع على الطلب {reference}. تعرض صفحة الطلب التقسيم "
            "والأسباب. تنتقل الأموال عند إرسال التسوية على السلسلة.",
        ),
    },
    "organization.invitation": {
        "en": (
            "You have been invited to join an organization",
            "An organization has invited you to join it as {role}.\n\nName given: "
            "{name}\nThat name was chosen by whoever sent the invitation and is not "
            "verified.\n\nYou are not a member until you accept, and you can decline. "
            "The invitation expires in 14 days.",
        ),
        "es": (
            "Te han invitado a unirte a una organización",
            "Una organización te ha invitado a unirte como {role}.\n\nNombre indicado: "
            "{name}\nEse nombre lo eligió quien envió la invitación y no está "
            "verificado.\n\nNo eres miembro hasta que aceptes, y puedes rechazarla. La "
            "invitación caduca en 14 días.",
        ),
        "fr": (
            "Vous avez été invité à rejoindre une organisation",
            "Une organisation vous invite à la rejoindre en tant que {role}.\n\nNom "
            "indiqué : {name}\nCe nom a été choisi par l'expéditeur de l'invitation et "
            "n'est pas vérifié.\n\nVous n'êtes pas membre tant que vous n'avez pas "
            "accepté, et vous pouvez refuser. L'invitation expire dans 14 jours.",
        ),
        "de": (
            "Sie wurden in eine Organisation eingeladen",
            "Eine Organisation hat Sie als {role} eingeladen.\n\nAngegebener Name: "
            "{name}\nDieser Name wurde von der einladenden Person gewählt und ist nicht "
            "überprüft.\n\nSie sind erst Mitglied, wenn Sie annehmen, und können "
            "ablehnen. Die Einladung läuft in 14 Tagen ab.",
        ),
        "pt": (
            "Foi convidado para entrar numa organização",
            "Uma organização convidou-o a entrar como {role}.\n\nNome indicado: {name}\n"
            "Esse nome foi escolhido por quem enviou o convite e não é verificado.\n\n"
            "Só é membro depois de aceitar, e pode recusar. O convite expira em 14 dias.",
        ),
        "ja": (
            "組織への参加に招待されました",
            "ある組織があなたを {role} として招待しています。\n\n提示された名称: {name}\n"
            "この名称は招待した側が設定したもので、検証されていません。\n\n承諾するまで"
            "メンバーにはならず、辞退もできます。招待は14日で期限切れになります。",
        ),
        "ko": (
            "조직 참여 초대를 받았습니다",
            "한 조직이 귀하를 {role} 로 초대했습니다.\n\n제시된 이름: {name}\n이 이름은 "
            "초대를 보낸 쪽이 정한 것이며 검증되지 않았습니다.\n\n수락하기 전까지는 "
            "구성원이 아니며 거절할 수 있습니다. 초대는 14일 후 만료됩니다.",
        ),
        "zh": (
            "你被邀请加入一个组织",
            "有组织邀请你以 {role} 身份加入。\n\n所给名称：{name}\n该名称由发出邀请的一方"
            "填写，未经验证。\n\n在你接受之前你不是成员，你也可以拒绝。邀请将在 14 天后失效。",
        ),
        "ar": (
            "تمت دعوتك للانضمام إلى مؤسسة",
            "دعتك مؤسسة للانضمام إليها بصفة {role}.\n\nالاسم المذكور: {name}\nاختار هذا "
            "الاسم من أرسل الدعوة وهو غير موثق.\n\nلن تصبح عضواً حتى تقبل، ويمكنك "
            "الرفض. تنتهي صلاحية الدعوة خلال 14 يوماً.",
        ),
    },
}


def placeholders(template: str) -> set[str]:
    """The named fields a template expects."""
    return {name for _, name, _, _ in Formatter().parse(template) if name}


def render(key: str, locale: str | None, /, **params: object) -> tuple[str, str]:
    """The title and body for an event, in the recipient's language.

    Falls back to English for an unknown or unsupported locale rather than
    raising, because a notification that cannot be phrased is still a notification
    somebody needs. It falls back for the whole message, not field by field, so a
    recipient never gets a title in one language and a body in another.
    """
    catalogue = MESSAGES[key]
    chosen = locale if locale in catalogue else FALLBACK
    title, body = catalogue[chosen]
    return title.format(**params), body.format(**params)


def localise_url(url: str | None, locale: str | None, /) -> str | None:
    """Point a link at the language the message around it is written in.

    Every page on the site lives under a locale segment, and a link without one
    is resolved by the browser's `Accept-Language` rather than by the account.
    So a subscriber whose language is Japanese received a Japanese email whose
    link landed them on the English page, because their browser said English.
    The message and its destination disagreed.

    This lives beside `render` deliberately. Both have to make the same choice
    from the same locale, including the same fallback, and separating them is
    how a body in one language acquires a link in another.

    Left alone: anything that is not one of our own URLs, and anything already
    carrying a locale segment.
    """
    if not url:
        return url

    from app.core.config import settings

    base = settings.APP_URL.rstrip("/")
    if not url.startswith(base):
        return url

    rest = url[len(base):]
    if rest and not rest.startswith(("/", "?", "#")):
        # A different host that merely shares this prefix, not a path of ours.
        return url

    # Split the path from a query string or fragment, keeping whichever it was.
    cut = min((i for i in (rest.find("?"), rest.find("#")) if i != -1), default=len(rest))
    path, suffix = rest[:cut], rest[cut:]

    segments = [s for s in path.split("/") if s]
    if segments and segments[0] in LOCALES:
        return url

    chosen = locale if locale in LOCALES else FALLBACK
    return f"{base}/{chosen}" + ("/" + "/".join(segments) if segments else "") + suffix
