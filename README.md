# 🎙️ ملاك — Malak Calls

تطبيق ويب لإدارة المهام وطلب مكالمة هاتفية بصوت ملاك عند إنجاز مهمة، أو عند ضغط زر تجربة الاتصال.

## نشر التطبيق على Render
1. افتح https://dashboard.render.com/ واختر New > Blueprint، ثم اربط مستودع `SilvrSA/Call-for-finesh`.
2. اضبط متغيرات البيئة المطلوبة في Render: `MALAK_PASSWORD`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `MALAK_TO_NUMBER` بالصيغة الدولية `+966...`.
3. ينشئ Render سر الجلسة `FLASK_SECRET_KEY` تلقائيًا من `render.yaml`.
4. افتح رابط HTTPS الناتج على الآيفون عبر Safari، ثم مشاركة > إضافة إلى الشاشة الرئيسية. افتح الرابط نفسه من الكمبيوتر.

**هام:** لا تحفظ كلمات المرور أو رموز Twilio في GitHub. رمز `MALAK_PASSWORD` مطلوب ولا يوجد رمز افتراضي جاهز للإنتاج. يرسل التطبيق *طلب اتصال* ولا يضمن وصول المكالمة. يجب تفعيل المكالمات الدولية للسعودية ورقم مرسل مؤهل، وقد تُفرض رسوم. الصوت الافتراضي `Polly.Hala-Neural` باللغة `ar-AE` ويمكن تغييره بالمتغيرين `MALAK_VOICE` و`MALAK_LANGUAGE`.

**تنبيه:** هذا إصدار أولي. بيانات المهام مخزنة محليًا في حاوية Render تحت `/tmp`، وقد تختفي مع إعادة التشغيل. لا يوجد بعد تزامن دائم أو تنفيذ مستقل لمهام ChatGPT. اتصالات Twilio لا تعمل حتى إعداد الحساب.

## تجربة محلية
```bash
pip install -r requirements.txt
export MALAK_PASSWORD=choose-a-long-password
export FLASK_SECRET_KEY=choose-another-long-random-secret
python app.py
```
زر Test لا يجري اتصالًا عند غياب إعدادات Twilio.
