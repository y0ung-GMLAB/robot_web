#include "xtouch_midi/xtouch_node.hpp"

#include <algorithm>
#include <cctype>
#include <functional>
#include <cstdio>
#include <stdexcept>

namespace
{

constexpr std::size_t kNumChannels = 8;
constexpr uint8_t kButton0NoteStart = 0;
constexpr uint8_t kButton1NoteStart = 8;
constexpr uint8_t kButton2NoteStart = 16;
constexpr uint8_t kButton3NoteStart = 24;
constexpr uint8_t kDialCcStart = 16;
constexpr uint8_t kDialCcEnd = kDialCcStart + kNumChannels - 1;
constexpr uint8_t kFaderTouchNoteStart = 104;
constexpr uint8_t kFaderTouchNoteEnd = kFaderTouchNoteStart + kNumChannels - 1;
constexpr uint8_t kDisplayCharsPerChannel = 7;
constexpr uint8_t kDisplayBottomRowOffset = kDisplayCharsPerChannel * kNumChannels;
constexpr int32_t kFaderValueMax = 16383;
constexpr int32_t kDialValueMax = 127;
constexpr auto kDebounceInterval = std::chrono::milliseconds(100);
constexpr auto kDebounceTick = std::chrono::milliseconds(50);

std::string to_upper(std::string s)
{
  std::transform(
    s.begin(), s.end(), s.begin(),
    [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
  return s;
}

bool looks_like_xtouch(const std::string & port_name)
{
  const std::string up = to_upper(port_name);
  return up.find("X-TOUCH") != std::string::npos ||
         up.find("XTOUCH") != std::string::npos ||
         up.find("BEHRINGER") != std::string::npos;
}

template<typename T>
std::vector<T> to_vector(const std::array<T, kNumChannels> & values)
{
  return std::vector<T>(values.begin(), values.end());
}

}  // namespace

namespace xtouch_midi
{

template<typename Port>
void XTouchNode::open_matching_port(Port & port, const char * direction)
{
  const unsigned int n = port.getPortCount();

  for (unsigned int i = 0; i < n; ++i) {
    const std::string name = port.getPortName(i);
    if (looks_like_xtouch(name)) {
      port.openPort(i);
      return;
    }
  }

  throw std::runtime_error(
    std::string("No MIDI ") + direction +
    " port matching 'X-Touch'/'XTOUCH'/'Behringer' found. "
    "Is the device connected and powered on?");
}

XTouchNode::XTouchNode(const rclcpp::NodeOptions & options)
: rclcpp::Node("xtouch_node", options)
{
  const std::string midi_topic =
    declare_parameter<std::string>("midi_topic", "/xtouch/midi");
  const auto publish_period_param =
    declare_parameter<int64_t>("publish_period_ms", 5);
  const auto publish_period =
    std::chrono::milliseconds(std::max<int64_t>(1, publish_period_param));
  const int initial_dial_value = declare_parameter<int>("initial_dial_value", 0);
  encoder_relative_mode_ = declare_parameter<bool>("encoder_relative_mode", true);
  button_led_feedback_ = declare_parameter<bool>("button_led_feedback", true);
  display_feedback_ = declare_parameter<bool>("display_feedback", true);
  const auto display_device_id_param =
    declare_parameter<int64_t>("display_device_id", 0x15);
  display_device_id_ = static_cast<uint8_t>(
    std::clamp<int64_t>(display_device_id_param, 0, 127));

  dial_.fill(std::clamp(initial_dial_value, 0, kDialValueMax));

  midi_pub_ = create_publisher<MidiMsg>(
    midi_topic, rclcpp::QoS(1).best_effort());

  midi_in_ = std::make_unique<RtMidiIn>();
  midi_in_->ignoreTypes(true, true, true);
  midi_in_->setCallback(&XTouchNode::midi_trampoline, this);
  open_matching_port(*midi_in_, "input");

  midi_out_ = std::make_unique<RtMidiOut>();
  open_matching_port(*midi_out_, "output");
  for (uint8_t note = kButton0NoteStart;
    note < kButton3NoteStart + kNumChannels; ++note)
  {
    send_button_led(note, false);
  }
  for (uint8_t ch = 0; ch < kNumChannels; ++ch) {
    send_channel_dial_display(ch, dial_[ch]);
  }

  publish_tick_ = create_wall_timer(
    publish_period, std::bind(&XTouchNode::publish_state, this));

  debounce_tick_ = create_wall_timer(
    kDebounceTick, std::bind(&XTouchNode::tick_debounce, this));
}

XTouchNode::~XTouchNode()
{
  if (midi_in_) {
    midi_in_->cancelCallback();
    if (midi_in_->isPortOpen()) {
      midi_in_->closePort();
    }
  }
  if (midi_out_ && midi_out_->isPortOpen()) {
    midi_out_->closePort();
  }
}

void XTouchNode::midi_trampoline(
  double /* timestamp */,
  std::vector<unsigned char> * msg,
  void * user_data)
{
  if (msg == nullptr || user_data == nullptr) {
    return;
  }
  static_cast<XTouchNode *>(user_data)->on_midi(*msg);
}

void XTouchNode::on_midi(const std::vector<unsigned char> & bytes)
{
  if (bytes.size() < 3) {
    return;
  }

  const uint8_t status = bytes[0] & 0xF0;
  const uint8_t midi_channel = bytes[0] & 0x0F;
  const uint8_t d1 = bytes[1];
  const uint8_t d2 = bytes[2];

  if (status == 0xE0 && midi_channel < kNumChannels) {
    const int32_t value = static_cast<int32_t>((d2 << 7) | d1);
    set_fader_value(midi_channel, value);
  } else if (status == 0xB0 && d1 >= kDialCcStart && d1 <= kDialCcEnd) {
    const std::size_t ch = d1 - kDialCcStart;
    int32_t value = 0;
    bool changed = false;
    {
      std::lock_guard<std::mutex> lk(state_mutex_);
      const int32_t old_value = dial_[ch];
      if (encoder_relative_mode_) {
        dial_[ch] = std::clamp(
          dial_[ch] + encoder_delta(d2), int32_t{0}, kDialValueMax);
      } else {
        dial_[ch] = std::clamp<int32_t>(d2, 0, kDialValueMax);
      }
      value = dial_[ch];
      changed = value != old_value;
    }
    if (changed) {
      send_channel_dial_display(static_cast<uint8_t>(ch), value);
    }
  } else {
    const bool note_event =
      status == 0x90 || status == 0x80;
    if (note_event) {
      const bool pressed = status == 0x90 && d2 > 0;
      if (d1 >= kFaderTouchNoteStart && d1 <= kFaderTouchNoteEnd) {
        const std::size_t ch = d1 - kFaderTouchNoteStart;
        {
          std::lock_guard<std::mutex> lk(state_mutex_);
          touch_[ch] = pressed;
        }
      } else {
        toggle_button_state(d1, pressed);
      }
    }
  }
}

void XTouchNode::set_fader_value(uint8_t ch, int32_t value)
{
  std::lock_guard<std::mutex> lk(state_mutex_);
  channel_[ch] = std::clamp<int32_t>(value, 0, kFaderValueMax);
  btn3_requires_fader_update_[ch] = false;
  debounce_deadline_[ch] =
    std::chrono::steady_clock::now() + kDebounceInterval;
}

void XTouchNode::publish_state()
{
  MidiMsg msg;
  {
    std::lock_guard<std::mutex> lk(state_mutex_);
    msg.btn0 = to_vector(btn0_);
    msg.btn1 = to_vector(btn1_);
    msg.btn2 = to_vector(btn2_);
    msg.btn3 = to_vector(btn3_);
    for (std::size_t ch = 0; ch < msg.btn3.size(); ++ch) {
      msg.btn3[ch] = msg.btn3[ch] && !btn3_requires_fader_update_[ch];
    }
    msg.touch = to_vector(touch_);
    msg.channel = to_vector(channel_);
    msg.dial = to_vector(dial_);
  }
  midi_pub_->publish(msg);
}

void XTouchNode::tick_debounce()
{
  const auto now = std::chrono::steady_clock::now();
  for (std::size_t ch = 0; ch < kNumChannels; ++ch) {
    int32_t value = 0;
    bool fire = false;
    {
      std::lock_guard<std::mutex> lk(state_mutex_);
      if (debounce_deadline_[ch].has_value() &&
        now >= *debounce_deadline_[ch])
      {
        value = channel_[ch];
        debounce_deadline_[ch].reset();
        fire = true;
      }
    }
    if (fire) {
      send_fader_pitch_bend(static_cast<uint8_t>(ch), value);
    }
  }
}

void XTouchNode::send_fader_pitch_bend(uint8_t ch, int32_t value)
{
  if (!midi_out_) {
    return;
  }

  value = std::clamp<int32_t>(value, 0, kFaderValueMax);
  std::vector<unsigned char> bytes = {
    static_cast<unsigned char>(0xE0 | (ch & 0x0F)),
    static_cast<unsigned char>(value & 0x7F),
    static_cast<unsigned char>((value >> 7) & 0x7F),
  };

  try {
    midi_out_->sendMessage(&bytes);
  } catch (const RtMidiError &) {
  }
}

void XTouchNode::send_button_led(uint8_t note, bool on)
{
  if (!button_led_feedback_ || !midi_out_) {
    return;
  }

  std::vector<unsigned char> bytes = {
    static_cast<unsigned char>(0x90),
    note,
    static_cast<unsigned char>(on ? 127 : 0),
  };

  try {
    midi_out_->sendMessage(&bytes);
  } catch (const RtMidiError &) {
  }
}

void XTouchNode::send_display_text(uint8_t offset, const std::string & text)
{
  if (!display_feedback_ || !midi_out_) {
    return;
  }

  std::vector<unsigned char> bytes = {
    0xF0,
    0x00,
    0x00,
    0x66,
    display_device_id_,
    0x12,
    offset,
  };

  for (char c : text) {
    bytes.push_back(static_cast<unsigned char>(c) & 0x7F);
  }
  bytes.push_back(0xF7);

  try {
    midi_out_->sendMessage(&bytes);
  } catch (const RtMidiError &) {
  }
}

void XTouchNode::send_channel_dial_display(uint8_t ch, int32_t value)
{
  if (ch >= kNumChannels) {
    return;
  }

  const auto format_7 = [](const char * input) {
    std::string text(input);
    if (text.size() > kDisplayCharsPerChannel) {
      text.resize(kDisplayCharsPerChannel);
    }
    while (text.size() < kDisplayCharsPerChannel) {
      text.push_back(' ');
    }
    return text;
  };

  char label[8] = {};
  char number[8] = {};
  std::snprintf(label, sizeof(label), "DIAL%u", static_cast<unsigned int>(ch));
  std::snprintf(number, sizeof(number), "%3d", value);

  const uint8_t top_offset = ch * kDisplayCharsPerChannel;
  const uint8_t bottom_offset = kDisplayBottomRowOffset + top_offset;
  send_display_text(top_offset, format_7(label));
  send_display_text(bottom_offset, format_7(number));
}

bool XTouchNode::toggle_button_state(uint8_t note, bool pressed)
{
  if (!pressed) {
    return false;
  }

  std::array<bool, kNumChannels> * target = nullptr;
  std::array<bool, kNumChannels> * requires_fader_update = nullptr;
  std::size_t ch = 0;

  if (note >= kButton0NoteStart && note < kButton0NoteStart + kNumChannels) {
    target = &btn0_;
    ch = note - kButton0NoteStart;
  } else if (note >= kButton1NoteStart &&
    note < kButton1NoteStart + kNumChannels)
  {
    target = &btn1_;
    ch = note - kButton1NoteStart;
  } else if (note >= kButton2NoteStart &&
    note < kButton2NoteStart + kNumChannels)
  {
    target = &btn2_;
    ch = note - kButton2NoteStart;
  } else if (note >= kButton3NoteStart &&
    note < kButton3NoteStart + kNumChannels)
  {
    target = &btn3_;
    requires_fader_update = &btn3_requires_fader_update_;
    ch = note - kButton3NoteStart;
  } else {
    return false;
  }

  bool enabled = false;
  {
    std::lock_guard<std::mutex> lk(state_mutex_);
    (*target)[ch] = !(*target)[ch];
    enabled = (*target)[ch];
    if (requires_fader_update != nullptr) {
      (*requires_fader_update)[ch] = enabled;
    }
  }
  send_button_led(note, enabled);
  return true;
}

int32_t XTouchNode::encoder_delta(uint8_t value) const
{
  if (value == 0 || value == 64) {
    return 0;
  }
  if (value < 64) {
    return value;
  }
  return -static_cast<int32_t>(value - 64);
}

}  // namespace xtouch_midi

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  try {
    auto node = std::make_shared<xtouch_midi::XTouchNode>();
    rclcpp::spin(node);
  } catch (const RtMidiError &) {
    rclcpp::shutdown();
    return 2;
  } catch (const std::exception &) {
    rclcpp::shutdown();
    return 1;
  }
  rclcpp::shutdown();
  return 0;
}
